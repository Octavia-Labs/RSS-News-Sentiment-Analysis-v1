import feedparser
import schedule
import time
from datetime import datetime
import openai
from openai import ChatCompletion
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, ForeignKey, DateTime
from sqlalchemy.orm import sessionmaker, relationship
from sqlalchemy.ext.declarative import declarative_base
from dateutil.parser import parse
import json
from bs4 import BeautifulSoup
from urllib.parse import quote
import requests

engine = create_engine('postgresql://postgres:####@localhost/####')  # replace with your actual db connection string

Base = declarative_base()

class RssNewsItem(Base):
	__tablename__ = 'rss_news_items'

	id = Column(Integer, primary_key=True)
	title = Column(String)
	link = Column(String)
	published = Column(DateTime)
	summary = Column(Text)
	content = Column(Text)
	description = Column(Text)

class RssNewsSentiment(Base):
	__tablename__ = 'rss_news_sentiment'
	
	id = Column(Integer, primary_key=True)
	crypto_type = Column(String)
	crypto_name = Column(String)
	symbol = Column(String)
	org_name = Column(String)
	sentiment_score = Column(Float)
	movement_score = Column(Float)
	indicator_certainty = Column(Float)
	sentiment_timestamp = Column(DateTime)
	best_match_cmc_id = Column(String)
	best_match_cmc_name = Column(String)
	best_match_cmc_match_score = Column(Float)
	best_match_coinpaprika_id = Column(String)
	best_match_coinpaprika_match_score = Column(Float)
	newsitem_id = Column(Integer, ForeignKey('rss_news_items.id'))


Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)


def get_cmc_closest_match(name):
	try:
		url = 'https://octavia-kb-api.azurewebsites.net/fuzzy_search_cmc_tokens?api_key=g]gh4gh:S(Dhg;84wFG&searchterms=' + quote(name)
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
		url = 'https://octavia-kb-api.azurewebsites.net/fuzzy_search_coinpaprika?api_key=g]gh4gh:S(Dhg;84wFG&searchterms=' + quote(name)
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


RECOMPUTE_ALL=True
def update():
	session = Session()

	rows = session.query(RssNewsSentiment)
	for r in rows:
		if not r.best_match_cmc_id or RECOMPUTE_ALL:
			cmc_match = get_cmc_closest_match(r.crypto_name)
			coinpaprika_match = get_coinpaprika_closest_match(r.crypto_name)
			print(r.crypto_name, '--', cmc_match['id'], cmc_match['name'], cmc_match['score'], coinpaprika_match['id'], coinpaprika_match['score'])
			r.best_match_cmc_id = cmc_match['id']
			r.best_match_cmc_name = cmc_match['name']
			r.best_match_cmc_match_score = cmc_match['score']
			r.best_match_coinpaprika_id = coinpaprika_match['id']														
			r.best_match_coinpaprika_match_score = coinpaprika_match['score']
			session.commit()


update()
