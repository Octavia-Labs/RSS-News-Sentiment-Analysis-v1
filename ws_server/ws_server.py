import asyncio
import websockets
import json
from dotenv import load_dotenv
import os
from utils.helper_functions import loginfo, logerror, logdebug
import threading
from queue import Queue
import signal

server=None
terminate_flag=None

load_dotenv()
WS_SHARED_SECRET=os.getenv("WS_SHARED_SECRET")

# Create a thread-safe queue to store outgoing messages
message_queue = Queue()

# Define a set to store connected clients
connected_clients = set()

async def handle_client(websocket, path):
	# Wait for the client to provide the authentication secret during the handshake
	client_secret = await websocket.recv()
	
	# Check if the provided secret matches the shared secret
	if client_secret != WS_SHARED_SECRET:
		logerror('Client auth failed, closing connection...')
		# If the secret is invalid, close the connection
		await websocket.close()
		return
	loginfo('Client auth successful')	

	# Add the client to the set of connected clients
	connected_clients.add(websocket)
	loginfo(len(connected_clients),'clients connected')
	try:
		# Wait for the client connection to close
		await websocket.wait_closed()
	except websockets.exceptions.ConnectionClosedError:
		loginfo('Client connection closed')
		# Remove the client from the set if the connection is closed
		connected_clients.remove(websocket)
	except Exception as e:
		logerror('! handle_client exception')
		logerror(e)



async def start_server():
	# The IP address and port you want to run your WebSocket server on
	server_ip = "0.0.0.0"
	server_port = 8765

	# Start the WebSocket server
	server = await websockets.serve(handle_client, server_ip, server_port)
	loginfo(f"WebSocket server started at ws://{server_ip}:{server_port}")

	# Keep the server running indefinitely
	await server.wait_closed()

def run_server():
	global terminate_flag
	# Add a signal handler to stop the server gracefully on termination signals
	loop = asyncio.get_event_loop()
	#for signame in {'SIGINT', 'SIGTERM'}:
	#	loop.add_signal_handler(getattr(signal, signame), stop_server)

	# Start the server asynchronously
	loop.create_task(start_server())

	# Check the termination flag on each iteration
	while not terminate_flag:
		loop.run_until_complete(asyncio.sleep(0.5))

	loop.run_until_complete(stop_server())
	loginfo('Ws server closing')
	loop.close()
	loginfo('Ws server terminated')

async def stop_server():
	# Get all running tasks:
	tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]

	# Cancel all tasks:
	[task.cancel() for task in tasks]

	# Wait for tasks to be cancelled. 
	await asyncio.gather(*tasks, return_exceptions=True)

async def send_message(client, message):
	await client.send(message)

async def handle_message_queue():
	while True:
		# Check the message queue for outgoing messages
		while not message_queue.empty():
			message = message_queue.get()
			# Send the message to all connected clients
			for client in connected_clients:
					await client.send(message)
		await asyncio.sleep(0.1)

async def main():
	# Start the server and the message handling loop as concurrent tasks
	server_task = asyncio.create_task(start_server())
	message_handler_task = asyncio.create_task(handle_message_queue())

	# Poll the termination flag
	while not terminate_flag:
		await asyncio.sleep(1)  # Sleep for a short while to avoid busy-waiting

	# If termination flag is set, cancel the tasks
	server_task.cancel()
	message_handler_task.cancel()
	await asyncio.gather(server_task, message_handler_task, return_exceptions=True)
