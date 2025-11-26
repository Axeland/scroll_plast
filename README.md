# ScrollPlast: A Cross-Chain Bridge Event Listener Simulation

This repository contains a Python-based simulation of a critical component in a cross-chain bridge: the event listener. This component, often run by relayers or validators, is responsible for monitoring events on a source blockchain and triggering corresponding actions on a destination blockchain.

This simulation is designed as a robust, well-architected example that demonstrates best practices for building components of a decentralized system, including configuration management, modular design, error handling, and interaction with external services.

## Concept

In a typical cross-chain bridge, a user locks or deposits assets (like ETH or ERC20 tokens) into a smart contract on a source chain (e.g., Ethereum). This action emits an on-chain event, such as `DepositMade`.

An off-chain service, the **Event Listener**, must securely and reliably detect this event. Upon detection, it validates the event data and triggers a transaction on the destination chain (e.g., Scroll, Polygon) to mint a corresponding wrapped token (e.g., WETH) for the user. This ensures that assets are represented 1:1 across chains.

`ScrollPlast` simulates this off-chain listener, providing the core logic to watch for, process, and relay these critical events.

## Code Architecture

The script is designed with a clear separation of concerns, organized into several main classes:

-   **`ConfigManager`**: Responsible for loading and validating all necessary configurations from a `.env` file. This includes RPC endpoints, private keys, contract addresses, and API keys. This approach keeps sensitive data and settings out of the main codebase.

-   **`BlockchainConnector`**: An abstraction layer over the `web3.py` library. It handles all direct interactions with blockchain nodes, such as creating web3 instances, connecting to RPCs, instantiating contract objects, and, most importantly, building, signing, and sending transactions with proper nonce management and error handling.

-   **`TransactionProcessor`**: This class contains the business logic for what to do when an event is detected. It receives event data, validates it, constructs the appropriate function call for the destination contract (e.g., `mint()`), fetches an optimal gas price from an external API, and uses the `BlockchainConnector` to execute the transaction.

-   **`BridgeEventListener`**: The main orchestrator. It uses the `BlockchainConnector` to connect to the source chain and continuously polls for new `DepositMade` events from the bridge contract. When an event is found, it passes the data to the `TransactionProcessor` to be handled.

### System Flow Diagram

```
 [User] --locks tokens--> [Source Chain Bridge Contract]
                                    |
                                    | emits Event (e.g., DepositMade)
                                    v
 [ScrollPlast Event Listener] <--polls for events--
       |
       | 1. Detects & validates event
       | 2. Passes to Processor
       v
 [Transaction Processor]
       |
       | 1. Constructs mint transaction
       | 2. Fetches gas price from API (requests)
       | 3. Uses BlockchainConnector to sign & send tx
       v
 [Destination Chain Bridge Contract] <--receives tx--
                                    |
                                    | mints wrapped tokens for User
                                    v
                                  [User]
```

## How it Works

1.  **Initialization**: The `main` function starts by instantiating the `ConfigManager` to load all required settings from the `.env` file.
2.  **Connection**: It then creates two instances of `BlockchainConnector`: one for the source chain (read-only) and one for the destination chain (read-write, configured with the relayer's private key).
3.  **Setup**: The `TransactionProcessor` and `BridgeEventListener` are initialized with the necessary connectors and contract details.
4.  **Polling Loop**: The `BridgeEventListener` starts its main `listen()` loop. It determines the latest block number and creates an event filter to watch for `DepositMade` events from that point forward.
5.  **Event Detection**: In each loop iteration, it queries the filter for new event entries.
6.  **Processing**: If new events are found, it iterates through them and passes each one to the `TransactionProcessor`.
7.  **Transaction Execution**: The `TransactionProcessor` performs the following steps for each event:
    a.  Logs a unique identifier for the event (e.g., from the transaction hash and log index) to prevent duplicate processing.
    b.  Constructs the `mint` function call with parameters from the event (user address, amount, etc.).
    c.  (Optional) If configured, makes an HTTP request via the `requests` library to an external gas oracle API to fetch a competitive gas price.
    d.  Calls the `build_and_send_tx` method on the destination chain's `BlockchainConnector`.
    e.  The connector handles nonce management, gas estimation, signing the transaction, sending it to the network, and waiting for the receipt to confirm success or failure.
8.  **Logging**: Throughout the entire process, detailed logs are printed to the console, showing the status of the listener, events found, and the outcome of each transaction.
9.  **Continuation**: The loop sleeps for a configured interval (`POLL_INTERVAL`) and then repeats, ensuring continuous monitoring.

## Usage

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/your-username/ScrollPlast.git
    cd ScrollPlast
    ```

2.  **Install dependencies:**
    Create a virtual environment and install the required packages.
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows use `venv\Scripts\activate`
    pip install -r requirements.txt
    ```

3.  **Create a configuration file:**
    Create a file named `.env` in the project's root directory and populate it with your specific details. Use the template below:

    ```env
    # RPC endpoint for the source chain (e.g., Ethereum Sepolia)
    SOURCE_CHAIN_RPC="https://sepolia.infura.io/v3/YOUR_INFURA_PROJECT_ID"

    # RPC endpoint for the destination chain (e.g., Scroll Sepolia)
    DESTINATION_CHAIN_RPC="https://sepolia-rpc.scroll.io"

    # Private key of the relayer wallet (MUST have funds on the destination chain for gas)
    # IMPORTANT: Do not expose this key. Use a dedicated, low-value wallet for testing.
    RELAYER_PRIVATE_KEY="0x...your_private_key..."

    # Deployed address of the bridge contract on the source chain
    SOURCE_BRIDGE_ADDRESS="0x...your_source_contract_address..."

    # Deployed address of the bridge contract on the destination chain
    DESTINATION_BRIDGE_ADDRESS="0x...your_destination_contract_address..."
    
    # Polling interval in seconds
    POLL_INTERVAL=15

    # Optional: For external gas price estimation (e.g., Etherscan API for the destination chain)
    GAS_API_URL="https://api-sepolia.scrollscan.com/api"
    GAS_API_KEY="YOUR_SCROLLSCAN_API_KEY"
    ```

4.  **Run the script:**
    Execute the main script from your terminal.
    ```bash
    python script.py
    ```

    The listener will start, and you will see log messages indicating its status.

    **Example Output:**
    ```
    INFO:root:--- Starting Bridge Event Listener ---
    INFO:root:Successfully connected to source chain (Chain ID: 11155111)
    INFO:root:Successfully connected to destination chain (Chain ID: 534351)
    INFO:root:Relayer address: 0xAbC...123
    INFO:root:Starting to listen for 'DepositMade' events on contract 0x... from block 'latest'
    INFO:root:Polling for new events... No new events found.
    INFO:root:Polling for new events...
    INFO:root:Found 1 new event(s).
    INFO:root:Processing event: {'args': {'user': '0x...', 'amount': 1000000000000000000}, 'transactionHash': ...}
    INFO:root:Building transaction to call 'mint' on contract 0x...
    INFO:root:Transaction sent successfully. Hash: 0x...
    INFO:root:Waiting for transaction receipt...
    INFO:root:Transaction confirmed in block 123456.
    ```