#from sqlalchemy import create_engine, text
#from sqlalchemy.exc import StatementError
import psycopg2
import re
import time
import threading
from utils.helper_functions import loginfo, logerror, logdebug

class DBPool:
	def __init__(self, host, port, database, user, password, pool_size):
		self.host = host
		self.port = port
		self.database = database
		self.user = user
		self.password = password
		self.pool_size = pool_size
		self.pool = {}
		self.lock = threading.Lock()

		for i in range(pool_size):
			db = Database(host, port, database, user, password)
			#db.connect()
			self.pool[i] = {'db': db, 'in_use': False}

	def __enter__(self):
		self.conn = self.get_conn()
		return self.conn

	def __exit__(self, exc_type, exc_val, exc_tb):
		with self.lock:
			#logdebug('releasing db lock')
			for conn_id, conn_info in self.pool.items():
				if conn_info['db'] == self.conn:
					conn_info['in_use'] = False
					break
	
	def get_conn(self):
		while True:
			with self.lock:
					for conn_id, conn_info in self.pool.items():
						if not conn_info['in_use']:
							conn_info['in_use'] = True
							#if conn_info['db'].is_connection_alive():
							return conn_info['db']
							#else:
							#		conn_info['in_use'] = False
			time.sleep(0.1)

	def close_connections(self):
		for conn_info in self.pool.values():
			conn_info['db'].close_connection()



class Database:
	def __init__(self, host, port, database, user, password):
		self.host = host
		self.port = port
		self.database = database
		self.user = user
		self.password = password
		self.connection = self.connect()

	def connect(self):
		loginfo("Attempting to connect...")
		connection = psycopg2.connect(
			host=self.host,
			port=self.port,
			dbname=self.database,
			user=self.user,
			password=self.password,
			keepalives=1,
        	keepalives_idle=30,
        	keepalives_interval=10,
        	keepalives_count=5
			)
		loginfo("Connected to the database")
		return connection


	# NOTE: if you are running mixed type multiple queries (e.g. selects and inserts) then set commit=True because it won't autodetect properly
	def execute_query(self, query, params=None, commit=False):
		result = None
		while True:
			try:
				if not self.connection:
					self.connection = self.connect()
				if self.connection.closed:
					self.connection = self.connect()
				cursor = self.connection.cursor()
				if params is None:
					cursor.execute(query)
				else:
					# Replace ":param" with "%(param)s" for psycopg2
					psycopg2_sql = re.sub(r'(?<!:):(\w+)', lambda m: "%(" + m.group(1) + ")s" if m.group(1) in params else m.group(0), query)
					if type(params) is list:
						psycopg2.extras.execute_values(cursor, psycopg2_sql, params, template=None, page_size=100)
					else:
						cursor.execute(psycopg2_sql, params)

					if commit or (not query.strip().lower().startswith(("select", "(select"))):
						self.connection.commit()
						#try:
							# this is to handle non-select statements that return vales (e.g. with RETURNING clause)
						#	result = cursor.fetchall()
						#	return result
						#except Exception as e:
						result = cursor.rowcount
				if cursor.description is not None:
					result = cursor.fetchall()

				#cursor.close()
				return result
			except (psycopg2.OperationalError, psycopg2.InternalError) as e:
				logerror(f"Error executing query: {e}")
				#try:
				#	if cursor:
				#		cursor.close()
				#except Exception as e:
				#	pass
				try:
					logerror('Attempting to rollback transaction...')
					self.connection.rollback()
					logerror('rollback success')
				except Exception as e:
					logerror("rollback failed")
					logerror(e)
				self.close_connection()
				time.sleep(5)  # Wait for 5 seconds before retrying
			except Exception as e:
				logerror(f"Error executing query: {e}")
				raise

	def close_connection(self):
		if self.connection:
			self.connection.close()
			self.connection = None
			loginfo("Connection to the database closed.")
