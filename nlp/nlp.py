import requests
from urllib.parse import quote


def get_cmc_closest_match(name):
	try:
		url = '###' + quote(name)
		result = requests.get(url).json()
		if result and result['data'] and result['data']['results']:
			best_match_data = result['data']['results'][0]
			best_match_id = best_match_data[7]
			best_match_name = best_match_data[1]
			match_score = best_match_data[0]
			return {
				'id': best_match_id,
				'name': best_match_name,
				'score': match_score
			}
	except Exception as e:
		print(e)

	return {
			'id': None,
			'name': None,
			'score': None
		}

def get_coinpaprika_closest_match(name):
	try:
		url = '###' + quote(name)
		result = requests.get(url).json()
		if result and result['data'] and result['data']['results']:
			best_match_data = result['data']['results'][0]
			best_match_id = best_match_data[1]
			match_score = best_match_data[0]
			return {
				'id': best_match_id,
				'score': match_score
			}
	except Exception as e:
		print(e)

	return {
			'id': None,
			'score': None
		}