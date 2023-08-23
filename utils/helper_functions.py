import time
import subprocess
from flask_jsonpify import jsonify
import os, random
import logging
import sys

my_logger = logging.getLogger('my_logger')
my_logger.setLevel(logging.DEBUG)
handler = logging.StreamHandler(sys.stdout)
handler.setLevel(logging.DEBUG)
my_logger.addHandler(handler)

def loginfo(*args, **kwargs):
    log_message = ' '.join(map(str, args))
    my_logger.info(log_message, **kwargs)

def logerror(*args, **kwargs):
    log_message = ' '.join(map(str, args))
    my_logger.error(log_message, **kwargs)

def logdebug(*args, **kwargs):
    log_message = ' '.join(map(str, args))
    my_logger.debug(log_message, **kwargs)

def retval_error(err, add_data = None):
	retval = dict()	
	retval['status'] = 0
	retval['error'] = err
	retval['data'] = []
	if (add_data):
		for key in add_data:
			retval[key] = add_data[key]	
	print(err)
	return jsonify(retval)

def is_int(s):
	try: 
		int(s)
		return True
	except ValueError:
		return False
	

# full performance logging on the chrome browsers eats up disk space like crazy (we need it to get http status codes)
# so, this command clears out any chrome temp folders that haven't been modified in last 20 mins
def delete_files_periodically(termination_flag):
	while not termination_flag[0]:
		try:
			#subprocess.run(['find', '/tmp', '-name', '.com.google.Chrome*', '-mmin', '+20', '-exec', 'rm', '-r', '{}', ';'])		
			subprocess.run(['find', '/tmp', '-name', '.com.google.Chrome*', '-mmin', '+20', '-exec', 'rm', '-r', '{}', ';'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
			# Check termination flag every second
			for _ in range(1200):
				if termination_flag[0]:
					print('terminating deletion thread')
					break
				time.sleep(0.1)  # Sleep for 0.1 second			
		except Exception as e:
			print(e)
			for _ in range(1200):
				if termination_flag[0]:
					print('terminating deletion thread')
					break
				time.sleep(0.1)  # Sleep for 0.1 second		
			

class LockFileManager:
	def __init__(self, lock_file_path):
		self.lock_file_path = lock_file_path

	def __enter__(self):
		while True:
			if os.path.exists(self.lock_file_path):
					modification_time = os.path.getmtime(self.lock_file_path)
					current_time = time.time()
					time_difference = current_time - modification_time
					if time_difference > 60:
						# Recreate the lock file in place
						with open(self.lock_file_path, 'a'):
							os.utime(self.lock_file_path, None)
						print("Lock file recreated.")

			if not os.path.exists(self.lock_file_path):
					try:
						with open(self.lock_file_path, 'w') as lock_file:
							lock_file.write('Lock')
						print("Lock file acquired.")
						break
					except IOError:
						# Failed to acquire lock, sleep for random duration before retrying
						random_sleep = random.uniform(0, 0.1)
						time.sleep(random_sleep)
			else:
					# Lock file exists, sleep for random duration before checking again
					random_sleep = random.uniform(0, 0.1)
					time.sleep(random_sleep)

	def __exit__(self, exc_type, exc_value, traceback):
		if os.path.exists(self.lock_file_path):
			os.remove(self.lock_file_path)
			print("Lock file released.")