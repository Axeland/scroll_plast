import os
import sys
import time
import json
import logging
from typing import Dict, Any, Optional

import requests
from dotenv import load_dotenv
from web3 import Web3
from web3.middleware import geth_poa_middleware
from web3.exceptions import TransactionNotFound

# Load environment variables from .env file
load_dotenv()

# --- Configuration & Constants ---

class ConfigManager:
    """A class to manage and validate configuration from environment variables."""
    def __init__(self):
        # RPC URLs for the source and destination chains
        self.SOURCE_CHAIN_RPC = os.getenv('SOURCE_CHAIN_RPC')
        self.DESTINATION_CHAIN_RPC = os.getenv('DESTINATION_CHAIN_RPC')

        # Private key for the relayer/validator wallet that will pay for gas on the destination chain
        self.RELAYER_PRIVATE_KEY = os.getenv('RELAYER_PRIVATE_KEY')

        # Bridge contract addresses
        self.SOURCE_BRIDGE_ADDRESS = os.getenv('SOURCE_BRIDGE_ADDRESS')
        self.DESTINATION_BRIDGE_ADDRESS = os.getenv('DESTINATION_BRIDGE_ADDRESS')

        # API key for gas price estimation (e.g., Etherscan)
        self.GAS_API_URL = os.getenv('GAS_API_URL') # Example: https://api.etherscan.io/api
        self.GAS_API_KEY = os.getenv('GAS_API_KEY')
        
        # Polling interval in seconds
        self.POLL_INTERVAL = int(os.getenv('POLL_INTERVAL', '15'))
        
        self.validate()

    def validate(self):
        """Validates that all necessary configuration variables are set."""
        required_vars = [
            'SOURCE_CHAIN_RPC', 'DESTINATION_CHAIN_RPC', 'RELAYER_PRIVATE_KEY',
            'SOURCE_BRIDGE_ADDRESS', 'DESTINATION_BRIDGE_ADDRESS'
        ]
        missing_vars = [var for var in required_vars if not getattr(self, var)]
        if missing_vars:
            raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# --- Custom Exceptions ---

class BlockchainConnectionError(Exception):
    """Custom exception for issues connecting to a blockchain node."""
    pass

class TransactionProcessingError(Exception):
    """Custom exception for failures during transaction processing and submission."""
    pass

# --- Blockchain Interaction Layer ---

class BlockchainConnector:
    """Handles low-level interactions with a blockchain via Web3.py."""
    def __init__(self, rpc_url: str, private_key: Optional[str] = None):
        """
        Initializes the connector.
        :param rpc_url: The HTTP RPC endpoint for the blockchain node.
        :param private_key: The private key of the account to be used for signing transactions.
        """
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))
        # Inject middleware for PoA chains like Goerli, Sepolia, etc.
        self.w3.middleware_onion.inject(geth_poa_middleware, layer=0)

        if not self.w3.is_connected():
            raise BlockchainConnectionError(f"Failed to connect to the node at {rpc_url}")

        self.account = None
        if private_key:
            self.account = self.w3.eth.account.from_key(private_key)
            self.address = self.account.address

        logging.info(f"Successfully connected to chain with ID: {self.w3.eth.chain_id}")

    def get_contract(self, address: str, abi: Dict) -> Any:
        """
        Returns a Web3 contract instance.
        :param address: The contract's address.
        :param abi: The contract's ABI.
        :return: A Web3.py contract object.
        """
        checksum_address = self.w3.to_checksum_address(address)
        return self.w3.eth.contract(address=checksum_address, abi=abi)

    def get_latest_block(self) -> int:
        """Returns the latest block number on the connected chain."""
        return self.w3.eth.block_number

    def build_and_send_tx(self, contract_function, gas_price_gwei: int) -> str:
        """
        Builds, signs, and sends a transaction.
        :param contract_function: The pre-filled contract function to call (e.g., contract.functions.mint(...)).
        :param gas_price_gwei: The gas price to use in Gwei.
        :return: The transaction hash as a hex string.
        """
        if not self.account:
            raise TransactionProcessingError("Private key not provided. Cannot send transactions.")

        try:
            nonce = self.w3.eth.get_transaction_count(self.address)
            tx_params = {
                'from': self.address,
                'nonce': nonce,
                'gasPrice': self.w3.to_wei(gas_price_gwei, 'gwei'),
            }
            
            # Estimate gas
            gas_estimate = contract_function.estimate_gas(tx_params)
            tx_params['gas'] = int(gas_estimate * 1.2) # Add a 20% buffer

            transaction = contract_function.build_transaction(tx_params)

            signed_tx = self.w3.eth.account.sign_transaction(transaction, self.account.key)
            tx_hash = self.w3.eth.send_raw_transaction(signed_tx.rawTransaction)

            logging.info(f"Transaction sent with hash: {tx_hash.hex()}")
            
            # Wait for transaction receipt
            receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=180)
            
            if receipt.status == 0:
                raise TransactionProcessingError(f"Transaction {tx_hash.hex()} failed (reverted).")
            
            logging.info(f"Transaction {tx_hash.hex()} confirmed successfully in block {receipt.blockNumber}.")
            return tx_hash.hex()

        except TransactionNotFound:
            raise TransactionProcessingError("Transaction was not found on the network after sending.")
        except Exception as e:
            logging.error(f"An error occurred while sending transaction: {e}")
            raise TransactionProcessingError(str(e))

# --- Core Logic Layer ---

class TransactionProcessor:
    """
    Processes events from the source chain and triggers transactions on the destination chain.
    """
    def __init__(self, dest_connector: BlockchainConnector, dest_bridge_contract: Any, gas_api_config: Dict):
        """
        Initializes the processor.
        :param dest_connector: BlockchainConnector for the destination chain.
        :param dest_bridge_contract: Web3 contract instance for the destination bridge.
        :param gas_api_config: Dictionary containing GAS_API_URL and GAS_API_KEY.
        """
        self.dest_connector = dest_connector
        self.dest_bridge_contract = dest_bridge_contract
        self.gas_api_config = gas_api_config
        # In a production system, this would be a persistent database (e.g., Redis, SQL).
        self.processed_events = set()

    def get_optimal_gas_price(self) -> int:
        """
        Fetches the optimal gas price from an external API (e.g., Etherscan).
        Falls back to the node's suggested gas price if the API fails.
        Returns gas price in Gwei.
        """
        if self.gas_api_config['url'] and self.gas_api_config['key']:
            try:
                params = {
                    'module': 'gastracker',
                    'action': 'gasoracle',
                    'apikey': self.gas_api_config['key']
                }
                response = requests.get(self.gas_api_config['url'], params=params, timeout=5)
                response.raise_for_status()
                data = response.json()
                if data['status'] == '1':
                    propose_gas_price = int(data['result']['ProposeGasPrice'])
                    logging.info(f"Fetched gas price from API: {propose_gas_price} Gwei")
                    return propose_gas_price
            except requests.RequestException as e:
                logging.warning(f"Could not fetch gas price from API: {e}. Falling back to node estimate.")

        # Fallback to node's gas price oracle
        fallback_price_wei = self.dest_connector.w3.eth.gas_price
        fallback_price_gwei = self.dest_connector.w3.to_wei(fallback_price_wei, 'gwei')
        logging.info(f"Using fallback gas price from node: {fallback_price_gwei} Gwei")
        return int(fallback_price_gwei)

    def process_deposit_event(self, event: Dict[str, Any]):
        """
        Handles a single 'DepositMade' event.
        """
        # Generate a unique identifier for the event to prevent re-processing
        event_id = f"{event['transactionHash'].hex()}-{event['logIndex']}"
        if event_id in self.processed_events:
            logging.warning(f"Event {event_id} has already been processed. Skipping.")
            return

        args = event['args']
        logging.info(f"Processing new event: User {args['user']} deposited {args['amount']} of token {args['token']}")

        try:
            # 1. Prepare the minting function call on the destination contract
            mint_function = self.dest_bridge_contract.functions.mint( 
                args['user'],
                args['amount'],
                args['token'],
                event['transactionHash'] # Use source tx hash as a nonce/ID to prevent replays
            )
            
            # 2. Get the optimal gas price
            gas_price = self.get_optimal_gas_price()

            # 3. Build and send the transaction
            tx_hash = self.dest_connector.build_and_send_tx(mint_function, gas_price)
            logging.info(f"Successfully processed event {event_id} with destination tx: {tx_hash}")

            # 4. Mark event as processed upon success
            self.processed_events.add(event_id)

        except TransactionProcessingError as e:
            logging.error(f"Failed to process event {event_id}: {e}")
        except Exception as e:
            logging.error(f"An unexpected error occurred while processing event {event_id}: {e}")


class BridgeEventListener:
    """
    Listens for events on the source chain bridge contract and orchestrates processing.
    """
    def __init__(self, config: ConfigManager, source_connector: BlockchainConnector, transaction_processor: TransactionProcessor):
        self.config = config
        self.source_connector = source_connector
        self.transaction_processor = transaction_processor
        
        # A simplified ABI for demonstration purposes
        self.source_bridge_abi = json.loads('[{"anonymous":false,"inputs":[{"indexed":true,"internalType":"address","name":"user","type":"address"},{"indexed":true,"internalType":"address","name":"token","type":"address"},{"indexed":false,"internalType":"uint256","name":"amount","type":"uint256"}],"name":"DepositMade","type":"event"}]')
        self.dest_bridge_abi = json.loads('[{"inputs":[{"internalType":"address","name":"to","type":"address"},{"internalType":"uint256","name":"amount","type":"uint256"},{"internalType":"address","name":"token","type":"address"},{"internalType":"bytes32","name":"sourceTxHash","type":"bytes32"}],"name":"mint","outputs":[],"stateMutability":"nonpayable","type":"function"}]')
        
        self.source_contract = self.source_connector.get_contract(
            self.config.SOURCE_BRIDGE_ADDRESS, self.source_bridge_abi
        )

    def listen(self):
        """Starts the main event listening loop."""
        logging.info(f"Starting event listener for contract {self.config.SOURCE_BRIDGE_ADDRESS}...")
        
        # Start polling from the latest block to avoid processing historical events on startup
        from_block = self.source_connector.get_latest_block()
        logging.info(f"Starting to poll from block {from_block}")

        event_filter = self.source_contract.events.DepositMade.create_filter(fromBlock=from_block)
        
        while True:
            try:
                latest_block = self.source_connector.get_latest_block()
                if event_filter.fromBlock > latest_block:
                    time.sleep(self.config.POLL_INTERVAL)
                    continue

                new_entries = event_filter.get_new_entries()
                if new_entries:
                    logging.info(f"Found {len(new_entries)} new event(s).")
                    for event in new_entries:
                        self.transaction_processor.process_deposit_event(event)
                else:
                    logging.info(f"No new events found up to block {latest_block}. Waiting...")

                # Move the filter's fromBlock forward
                event_filter = self.source_contract.events.DepositMade.create_filter(fromBlock=latest_block + 1)
                
                time.sleep(self.config.POLL_INTERVAL)

            except Exception as e:
                logging.error(f"Error in listening loop: {e}. Retrying in {self.config.POLL_INTERVAL} seconds.")
                time.sleep(self.config.POLL_INTERVAL)

# --- Main Execution ---

def main():
    """Main function to set up and run the listener."""
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    try:
        # 1. Load Configuration
        config = ConfigManager()
        logging.info("Configuration loaded successfully.")

        # 2. Set up blockchain connectors
        source_connector = BlockchainConnector(config.SOURCE_CHAIN_RPC)
        dest_connector = BlockchainConnector(config.DESTINATION_CHAIN_RPC, config.RELAYER_PRIVATE_KEY)
        logging.info("Blockchain connectors initialized.")

        # 3. Set up Transaction Processor
        dest_bridge_contract = dest_connector.get_contract(
            config.DESTINATION_BRIDGE_ADDRESS, 
            BridgeEventListener(config, source_connector, None).dest_bridge_abi # Re-using ABI definition
        )
        gas_api_config = {'url': config.GAS_API_URL, 'key': config.GAS_API_KEY}
        processor = TransactionProcessor(dest_connector, dest_bridge_contract, gas_api_config)
        logging.info("Transaction processor initialized.")

        # 4. Set up and run the Event Listener
        listener = BridgeEventListener(config, source_connector, processor)
        listener.listen()

    except ValueError as e:
        logging.error(f"Configuration error: {e}")
        sys.exit(1)
    except BlockchainConnectionError as e:
        logging.error(f"Blockchain connection error: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        logging.info("Shutdown signal received. Exiting gracefully.")
        sys.exit(0)
    except Exception as e:
        logging.critical(f"An unhandled critical error occurred: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
