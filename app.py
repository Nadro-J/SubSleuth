# Standard
import json
import os
import time
import uuid

# Third-party
from flask import Flask, render_template, request, session, make_response, flash, redirect, url_for
import pandas as pd
import plotly
import plotly.graph_objects as go
import requests
import yaml

# Local
from identity_manager import IdentityManager

# Load configuration from YAML file
with open('config.yaml', 'r') as file:
    config = yaml.safe_load(file)

app = Flask(__name__)
app.secret_key = 'CreateAsEcReTkEy'

# Directory to store temporary JSON files
if not os.path.exists("tmp"):
    os.makedirs("tmp")


def exec_graphql(address, limit, url):
    query = f'''
    query GatherTxInfo {{
      accountById(id: "{address}") {{
        id
        transfersFrom(orderBy: id_DESC, limit: {limit}) {{
          id
          amount
          timestamp
          extrinsicHash
          to {{
            id
          }}
        }}
        transfersTo(orderBy: id_DESC, limit: {limit}) {{
          id
          amount
          timestamp
          extrinsicHash
          from {{
            id
          }}
        }}
      }}
    }}
    '''

    headers = {"Content-Type": "application/json"}
    data = {"query": query}
    response = requests.post(url, headers=headers, data=json.dumps(data), timeout=180)
    if response.status_code == 200:
        return response.json()
    else:
        raise Exception(f"Query failed with status code {response.status_code}: {response.text}")


def is_file_older_than_24_hours(file_path):
    """Check if a file is older than 24 hours."""
    try:
        # Get the time the file was last modified
        file_modification_time = os.path.getmtime(file_path)
        current_time = time.time()
        # Compare the file's modification time to the current time
        return current_time - file_modification_time > 24 * 3600
    except FileNotFoundError:
        return True


@app.route('/handle_dropdown', methods=['POST'])
def handle_dropdown():
    selected_network = request.form.get('network')
    session['selected_network'] = selected_network
    session['selected_url'] = config[selected_network]['graphql']
    session['selected_rpc'] = config[selected_network]['rpc']

    rpc_url = session.get('selected_rpc', config[selected_network]['rpc'])

    manager = IdentityManager(rpc_url)
    # Check if the cache for identities is older than 24 hours
    if is_file_older_than_24_hours(f'./off-chain-querying/{selected_network}-identity.json'):
        manager.cache_identities(network=selected_network)

    # Check if the cache for super_of is older than 24 hours
    if is_file_older_than_24_hours(f'./off-chain-querying/{selected_network}-superof.json'):
        manager.cache_super_of(network=selected_network)

    return redirect(url_for('index'))


@app.route('/download-json', methods=['GET'])
def download_json():
    filename = session.get('json_file')
    if not filename:
        flash('No data available', 'error')
        return redirect(url_for('index'))  # Redirect to the index page or some other page

    filepath = os.path.join("tmp", filename)
    with open(filepath, 'r') as f:
        json_data = f.read()

    response = make_response(json_data)
    response.headers['Content-Disposition'] = f'attachment; filename={filename}'
    response.headers['Content-Type'] = 'application/json'
    return response


@app.route("/")
def index():
    selected_network = session.get('selected_network', 'polkadot')  # Default to 'polkadot' if not set
    return render_template('index.html', selected_network=selected_network)


@app.route('/address', methods=['GET', 'POST'])
def get_address():
    if request.method == 'POST':
        address = request.form['address']

    # Set the maximum number of transactions to look back on
    max_transactions = 1000
    selected_network = request.form.get('network')

    rpc_url = session.get('selected_rpc', config[selected_network]['rpc'])
    enotation = session.get('selected_enotation', config[selected_network]['e_notation'])
    manager = IdentityManager(rpc_url)

    # Retrieve the URL from session or fallback to Polkadot URL
    url = session.get('selected_url', config['polkadot']['graphql'])

    # Check if the URL is still None (or any other undesired value) and handle it
    if not url or url == 'None':
        # Fallback to a default URL or handle the error
        url = config['polkadot']['graphql']

    json_data = json.dumps(exec_graphql(address=address, limit=max_transactions, url=url), indent=4, cls=plotly.utils.PlotlyJSONEncoder)
    data = json.loads(json_data)

    if data['data']['accountById'] is None:
        return "No data available", 404

    # Generate a unique filename for this JSON data
    filename = str(uuid.uuid4()) + ".json"
    filepath = os.path.join("tmp", filename)

    # Save the JSON data to this file
    with open(filepath, 'w') as f:
        f.write(json_data)

    session['json_file'] = filename  # Store only the filename in the session

    # Parse JSON data
    transfers_from = data["data"]["accountById"]["transfersFrom"]
    transfers_to = data["data"]["accountById"]["transfersTo"]

    # Convert JSON data to a Pandas DataFrame
    from_df = pd.DataFrame(transfers_from)
    if not from_df.empty:
        from_df["From"] = address  # The address from which the funds are transferred is the current address
        from_df["To"] = from_df["to"].apply(lambda x: x["id"])
        from_df["Value"] = from_df["amount"].astype(float) / float(enotation)

    else:
        # Define what to do or return when the DataFrame is empty
        from_df = pd.DataFrame(columns=["From", "To", "Value"])

    to_df = pd.DataFrame(transfers_to)

    if not to_df.empty:
        to_df["From"] = to_df["from"].apply(lambda x: x["id"])
        to_df["To"] = address  # The address to which the funds are transferred is the current address
        to_df["Value"] = to_df["amount"].astype(float) / float(enotation)
    else:
        to_df = pd.DataFrame(columns=["From", "To", "Value"])

    df = pd.concat([from_df, to_df], ignore_index=True)

    # Sort by timestamp, from newest to oldest
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df.sort_values(by='timestamp', ascending=False)

    # Group by 'From' and 'To' and calculate the sum of 'Value'
    grouped_df = df.groupby(['From', 'To'])['Value'].sum().reset_index()

    # Prepare data for the Sankey diagram
    label_list = list(set(grouped_df['From'].tolist() + grouped_df['To'].tolist()))
    source_indices = [label_list.index(address) for address in grouped_df['From']]
    target_indices = [label_list.index(address) for address in grouped_df['To']]

    values = grouped_df['Value'].tolist()

    node_values = [0] * len(label_list)
    for i, value in enumerate(values):
        node_values[source_indices[i]] += value
        node_values[target_indices[i]] += value

    # Shortened labels for visualization
    short_label_list = [manager.shorten_address(address=address, network=selected_network) for address in label_list]
    node_customdata = [{"address": address, "value": value} for address, value in zip(label_list, node_values)]
    node_hovertemplate = 'Address: %{customdata.address}<br>Value: %{customdata.value:,.3f}<extra></extra>'

    # Define the Sankey diagram
    fig = go.Figure(data=[go.Sankey(
        node=dict(
            pad=20,
            thickness=10,
            line=dict(color="black", width=2),
            label=short_label_list,
            customdata=node_customdata,
            hovertemplate=node_hovertemplate,
        ),
        link=dict(
            source=source_indices,
            target=target_indices,
            line=dict(color="black", width=0.2),
            value=[x * 0.5 for x in grouped_df['Value'].tolist()],
            hoverinfo='skip'
        ),
        arrangement='fixed'
    )])

    fig.update_layout(
        autosize=True,
        margin=dict(t=25, b=25, l=25, r=25)
    )

    # Serialize the data for the Sankey diagram
    sankey_data = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    return sankey_data


if __name__ == '__main__':
    app.run(debug=True)
