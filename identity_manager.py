import json
from substrateinterface import SubstrateInterface


class IdentityManager:
    def __init__(self, rpc_url):
        self.substrate = SubstrateInterface(url=rpc_url)

    def shorten_address(self, address, network):
        identity = self.check_identity(address, network)
        if len(address) > 12 and identity == 'N/A':
            return address[:6] + "..." + address[-6:]
        return identity

    """
    Cache super_of off-chain
    """

    def cache_super_of(self, network):
        """
        :param network:
        :param address:
        :return: The super-identity of an alternative 'sub' identity together with its name, within that
        """
        result_tmp = {}
        result = self.substrate.query_map(
            module='Identity',
            storage_function='SuperOf',
            params=[])

        for key, values in result:
            result_tmp.update({key.value: values.value})

        with open(f'./off-chain-querying/{network}-superof.json', 'w') as identfile:
            json.dump(result_tmp, indent=4, fp=identfile)

    def check_cached_super_of(self, address, network):
        with open(f'./off-chain-querying/{network}-superof.json', 'r') as identfile:
            data = json.load(identfile)
            return data.get(address, None)

    def check_super_of(self, address, network):
        """
        :param address:
        :return: The super-identity of an alternative 'sub' identity together with its name, within that
        """
        result = self.check_cached_super_of(address, network)

        if result is not None:
            return result[0]
        else:
            return 0

    """
    Cache proxies off-chain
    """

    def cache_identities(self, network):
        """
        Fetches identities from the 'Identity' module using the 'IdentityOf' storage function,
        and stores the results in a JSON file.

        This function queries the 'Identity' module for identities, and then iterates over the results,
        storing each identity in a temporary dictionary. The dictionary keys are the identity keys,
        and the values are the corresponding identity values.

        After all identities have been stored in the dictionary, the function writes the dictionary
        to a JSON file named 'identity.json'. The JSON file is formatted with an indentation of 4 spaces.

        Raises:
            IOError: If the function cannot write to 'identity.json'.
            JSONDecodeError: If the function cannot serialize the dictionary to JSON.
        """
        result_tmp = {}
        result = self.substrate.query_map(
            module='Identity',
            storage_function='IdentityOf',
            params=[]
        )

        for key, values in result:
            result_tmp.update({key.value: values.value})

        with open(f'./off-chain-querying/{network}-identity.json', 'w') as identfile:
            json.dump(result_tmp, indent=4, fp=identfile)

    @staticmethod
    def check_cached_identity(address, network):
        with open(f'./off-chain-querying/{network}-identity.json', 'r') as identfile:
            data = json.load(identfile)
            return data.get(address, None)

    def check_identity(self, address, network):
        """
        :param network:
        :param address:
        :return: Information that is pertinent to identify the entity behind an account.
        """

        result = self.check_cached_identity(address=address, network=network)
        if result is None:
            super_of = self.check_super_of(address=address, network=network)

            if super_of:
                result = self.check_cached_identity(address=super_of, network=network)
            else:
                return 'N/A'

        display = result['info']['display']
        twitter = result['info']['twitter']

        if 'Raw' in twitter:
            if len(twitter['Raw']) > 0:
                return twitter['Raw']

        if 'Raw' in display:
            if len(display['Raw']) > 0:
                return display['Raw']

        return 'N/A'
