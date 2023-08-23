import schedule
import time
from sqlalchemy import create_engine, Column, Integer, String, Text, Float, ForeignKey, DateTime, Boolean
from db.db import DBPool
from sqlalchemy.ext.declarative import declarative_base
from dateutil.parser import parse
import json
from bs4 import BeautifulSoup
import sys
import os
from dotenv import load_dotenv
import threading
import signal
from nlp.nlp import get_cmc_closest_match, get_coinpaprika_closest_match
from openai_functions.openai import trim_text_to_token_limit, num_tokens_from_text, do_chat_completion
import ws_server.ws_server as ws_server
from utils.helper_functions import loginfo, logerror, logdebug
from threading import Thread
import asyncio
import requests
import feedparser
from datetime import datetime
# monkey patch feedparser because it has no timeout by default so will sometimes hang indefinitely
headers = {
    'User-Agent': 'Mozilla/5.0 (X11; Linux i686; rv:95.0) Gecko/20100101 Firefox/95.0'
}
feedparser.api._open_resource = lambda *args, **kwargs: requests.get(args[0], headers=headers, timeout=30).content

sys.stdout = os.fdopen(sys.stdout.fileno(), 'w', 1)  # 1 means line-buffering

load_dotenv()

POSTGRESQL_HOST=os.getenv("POSTGRESQL_HOST")
POSTGRESQL_PORT=int(os.getenv("POSTGRESQL_PORT"))
POSTGRESQL_USER=os.getenv("POSTGRESQL_USER")
POSTGRESQL_PW=os.getenv("POSTGRESQL_PW")
POSTGRESQL_DB=os.getenv("POSTGRESQL_DB")
CRYPTOPANIC_AUTH_TOKEN = os.getenv("CRYPTOPANIC_AUTH_TOKEN")
DB_POOL_SIZE=1

dbpool = DBPool(POSTGRESQL_HOST, POSTGRESQL_PORT, POSTGRESQL_DB, POSTGRESQL_USER, POSTGRESQL_PW, DB_POOL_SIZE)

# Global flag to signal thread termination
terminate_flag = False

server_thread=None

def stop_server():
	global server_thread
	loginfo('Shutting down ws server')
	server_thread.join()
	loginfo('Ws server thread joined')
	
def start_server():
	# Define the function to run the server in a separate thread
	def run_server_in_thread():
		loop = asyncio.new_event_loop()
		asyncio.set_event_loop(loop)
		asyncio.run(ws_server.main())		

	# Create a thread for the WebSocket server and start it
	global server_thread
	server_thread = Thread(target=run_server_in_thread)
	server_thread.start()

start_server()


def serialize_instance(instance):
	result = {}
	for key, value in instance.__dict__.items():
		if not key.startswith('_'):
			if isinstance(value, datetime):
					result[key] = value.isoformat()
			else:
					result[key] = value
	return result


def insert_rss_news_item(conn, newsitem):
	query = """
		INSERT INTO rss_news_items
		(title, link, published, summary, content, description, one_sentence_summary, two_sentence_summary, topic_keywords, impact_importance, is_crypto_news, source)
		VALUES
		(:title, :link, :published, :summary, :content, :description, :one_sentence_summary, :two_sentence_summary, :topic_keywords, :impact_importance, :is_crypto_news, :source)
		RETURNING id;
	"""
	params = newsitem.__dict__
	results = conn.execute_query(query, params)
	try:
		event_data = serialize_instance(newsitem)
		ws_server.message_queue.put(json.dumps({
			'type': 'newsitem',
			'data': event_data
		}))
	except Exception as e:
		logerror('! insert_rss_news_item exception')
		logerror(e)		
	return results[0][0]

def insert_rss_news_sentiment(conn, sentiment):
	query = """
		INSERT INTO rss_news_sentiment
		(crypto_type, crypto_name, symbol, org_name, sentiment_score, movement_score, indicator_certainty, sentiment_timestamp, best_match_cmc_id, best_match_cmc_name, best_match_cmc_match_score, best_match_coinpaprika_id, best_match_coinpaprika_match_score, newsitem_id)
		VALUES
		(:crypto_type, :crypto_name, :symbol, :org_name, :sentiment_score, :movement_score, :indicator_certainty, :sentiment_timestamp, :best_match_cmc_id, :best_match_cmc_name, :best_match_cmc_match_score, :best_match_coinpaprika_id, :best_match_coinpaprika_match_score, :newsitem_id);
	"""
	params = sentiment.__dict__
	conn.execute_query(query, params)
	try:
		event_data = serialize_instance(sentiment)
		del event_data['newsitem_id']
		ws_server.message_queue.put(json.dumps({
			'type': 'sentiment',
			'data': dict(event_data)
		}))
	except Exception as e:
		logerror('! insert_rss_news_item exception')
		logerror(e)

def check_existing_rss_news_item(conn, link, title):
	# we actually want to keep duplicate stories (e.g. same headline) if multiple news outlets are picking it up
	# because this reflects trends we want to be capturing
	# HOWEVER while we are using the cheap tier of cryptopanic api, we have to also check for duplicate titles
	# this is because our current cryptopanic plan doesn't give us the original source url, but rather a link to the article
	# summary on the cryptopanic site (so we can't rely on the url comparison alone)

	# Also check if title is in db because we might have overlap with cryptopanic since all urls from their api direct to cryptopanic website
	query = """
		SELECT id FROM rss_news_items WHERE link = :link OR title = :title;
	"""
	params = {'link': link, 'title': title}
	results = conn.execute_query(query, params)
	if results:
		return True
	else:
		return False	

PROMPT_TEMPLATE = """You are chatgpt, an expert in semantic analysis. Your task is to analyse the following crypto news item for sentiment about crypto coins & tokens:

<NEWS_ITEM>
[END ARTICLE]

Your task is to determine which cryptocurrency tokens/projects/chains are mentioned in a way that expresses positive or negative sentiment. You should ignore any that are only tangentially mentioned and not the subject of the news piece. Focus on the cryptos that any sentiment in the article meaningfully applies to. For each of these you should extract:

1. The type: defi token / coin / chain / exchange / stock / fiat / other
2. Its name
3. Sentiment: -10 to 10
4. Is the content of the article likely to correlate with price movement (-10 to 10), with -10 being strong downward movement and 10 being strong upward movement
5. How strongly does the content indicate this predicted movement? (0-10)

Give your answer in valid json format as per this example:

[
	{"type": "<type>", "name": "<name>", "symbol": "<symbol if known>", "org_name": "<organisation name if known>", "sentiment": [-10-10], "movement": [-10-10], "indicator_certainty": 0-10},
	...
]

Note: if there were no cryptos referenced with meaningful sentiment, return an empty list []. Remember: not include stocks or other entities; we are only interested in crypto coins & tokens.
"""

SUMMARY_PROMPT_TEMPLATE = """You are chatgpt, an expert crypto article summariser. Your task is to analyse the following crypto news item and give an importance rating and summary:

<NEWS_ITEM>
[END ARTICLE]

Your task is to:
1. Generate a one sentence summary
2. Generate a two sentence summary
3. Generate a list of keywords representing the primary topic of the article, separated by comma
4. Rate the impact & importance of the article (0-10)
5. Specify whether the news is about crypto (true/false)

Give your answer in valid json format as per this example, with no additional commentary:

{"one_sentence_summary": "<summary>", "two_sentence_summary": "<summary>", "topic_keywords": "<comma separated keywords>", "impact_importance": <rating 0-10>, "is_crypto_news": <true/false>}

Notes on impact_importance ratings:
This represents the impact to the crypto project or industry or whatever the topic is. The higher ratings (6+) should be reserved for news with strong impact or wide reaching consequences. Use the lower ratings (0-5) for news that is "everyday" run of the mill crypto news that won't make waves.
Many articles will be zero or low impact because of the nature of the news. You don't need to try to centre the impact ratings around 5.
Try to assess the article's impact to the crypto project (if the article is about specific one(s), or to the crypto market as a whole.
0 means no discernable impact (e.g. it's advertising, a how-to guide, a fluff post or otherwise has no impact)
1-4 means low-mid impact
5 means significant medium level impact
6-9 means medium to strong impact
10 means very strong impact
"""
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
	source = Column(Text)
	one_sentence_summary = Column(Text)
	two_sentence_summary = Column(Text)
	topic_keywords = Column(Text)
	impact_importance = Column(Integer)
	is_crypto_news = Column(Boolean)

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






# Note: I've picked these from the top 100 rss feeds from the link below, as at 2023-07-07
# https://blog.feedspot.com/cryptocurrency_rss_feeds/
rss_feeds = [
	"https://coinjournal.net/feed/",
	"https://bitcoinist.com/feed/",
	"https://www.newsbtc.com/feed/",
	"https://www.coinspeaker.com/news/feed/",
	"https://cryptopotato.com/feed/",
	"https://99bitcoins.com/feed/",
	"https://cryptobriefing.com/feed/",
	"https://crypto.news/feed/",
	"https://secondpriority.com/feed/",
	"https://blog.funexclub.com/feed/",
	"https://www.thecryptoape.com/feed",
	"https://cryptozen.today/feed/",
	"https://www.coinbackyard.com/feed/",
	"https://thecryptotime.com/feed/",
	"https://www.coinsclone.com/feed/",
	"https://medium.com/feed/coinmonks",
	"https://medium.com/feed/@cointradeIndia",
	"https://blog.bitfinex.com/feed/",
	"https://cryptoslate.com/feed/",
	"https://blog.bitmex.com/feed/",
	"https://coincheckup.com/blog/feed/",
	"https://bitcoinik.com/feed/",
	"https://coinchapter.com/feed/",
	"https://coingeek.com/feed/",
	"https://coinjournal.net/feed/",
	"https://cryptoticker.io/en/feed/",
	"https://blog.coinjar.com/rss/",
	"https://coincentral.com/news/feed/",
	"https://cryptosrus.com/feed/",
	"https://cryptoadventure.com/feed/",
	"https://www.bitcoinmarketjournal.com/feed/",
	"https://www.trustnodes.com/feed",
	"https://coinidol.com/rss2/",
	"https://www.cryptocointrade.com/feed/",
	"https://www.livebitcoinnews.com/feed/",
	"https://themerkle.com/feed/",
	"https://bitrss.com/rss.xml",
	"https://blockmanity.com/feed/",
	"https://blocktelegraph.io/feed/",
	"https://cryptowhat.com/feed/",
	"https://cryptodisrupt.com/feed/",
	"https://www.forbes.com/crypto-blockchain/feed/",
	"https://themarketscompass.substack.com/feed",
	"https://ambcrypto.com/feed/",
	"https://u.today/rss",
	"https://dailyhodl.com/feed/",
	"https://coinpedia.org/feed/",
	"https://insidebitcoins.com/feed",
	"https://www.crypto-news-flash.com/feed/",
	"https://www.cryptonewsz.com/feed/",
	"https://zycrypto.com/feed/",
	"https://www.financemagnates.com/cryptocurrency/feed/",
	"https://blockchain.news/rss",
	"https://thecryptobasic.com/feed/",
	"https://webscrypto.com/feed/",
	"https://stealthex.io/blog/feed/",
	"https://thenewscrypto.com/feed/",
	"https://blockonomi.com/feed/",
	"https://dailycoin.com/feed/"
]


#result = requests.get('https://cryptopanic.com/news/18798206/Ripple-Has-Partnered-With-The-Island-Nation')
#loginfo(result.content)
#soup = BeautifulSoup(result.content, features="html.parser")


def process_article(article, data):
	global terminate_flag
	# generate summary & impact rating
	response_content = do_chat_completion(SUMMARY_PROMPT_TEMPLATE, article, '<NEWS_ITEM>', 800, 5)
	if terminate_flag:
		return
	
	if not response_content:
		return

	# Parse the JSON response content
	summary_data = json.loads(response_content)
	# {"one_sentence_summary": "<summary>", "two_sentence_summary": "<summary>", "topic_keywords": "<comma separated keywords>", "impact_importance": <rating 0-10>, "is_crypto_news": <true/false>}
	if not all(k in summary_data for k in ("one_sentence_summary", "two_sentence_summary", "topic_keywords", "impact_importance", "is_crypto_news")):
		loginfo(f"Skipping news item because of invalid summary data.")
		loginfo(summary_data)
		return


	# generate sentiment data
	response_content = do_chat_completion(PROMPT_TEMPLATE, article, '<NEWS_ITEM>', 800, 5)
	if terminate_flag:
		return
	
	if not response_content:
		return

	# Parse the JSON response content
	responses = json.loads(response_content)

	# Store the news item and sentiment in the database

	newsitem = RssNewsItem(
		title=data['title'], 
		link=data['link'], 
		published=data['published'], 
		summary=data['summary'], 
		content=data['content'],
		description=data['description'],
		one_sentence_summary = summary_data['one_sentence_summary'],
		two_sentence_summary = summary_data['two_sentence_summary'],
		topic_keywords = summary_data['topic_keywords'],
		impact_importance = summary_data['impact_importance'],
		is_crypto_news = summary_data['is_crypto_news'],
		source = data['source']
	)
	with dbpool as conn:
		newsitem_id = insert_rss_news_item(conn, newsitem)

	for r in responses:
			# Check validity of required fields
			if not all(k in r for k in ("type", "name", "sentiment", "movement", "indicator_certainty")):
					loginfo(f"Skipping invalid sentiment data for news item {newsitem.id}")
					continue
			
			loginfo(r)
			cmc_match = get_cmc_closest_match(r.get('name'))
			coinpaprika_match = get_coinpaprika_closest_match(r.get('name'))

			sentiment = RssNewsSentiment(
					crypto_type=r.get('type'), 
					crypto_name=r.get('name'), 
					symbol=r.get('symbol'), 
					org_name=r.get('org_name'), 
					sentiment_score=r.get('sentiment'),
					movement_score=r.get('movement'),
					indicator_certainty=r.get('indicator_certainty'),
					sentiment_timestamp=data['published'], 
					best_match_cmc_id = cmc_match['id'],
					best_match_cmc_name = cmc_match['name'],
					best_match_cmc_match_score = cmc_match['score'],
					best_match_coinpaprika_id = coinpaprika_match['id'],																		
					best_match_coinpaprika_match_score = coinpaprika_match['score'],
					newsitem_id=newsitem_id
			)
			insert_rss_news_sentiment(conn, sentiment)
	

def check_cryptopanic():
	global terminate_flag	
	url = 'https://cryptopanic.com/api/v1/posts/?auth_token='+CRYPTOPANIC_AUTH_TOKEN+'&metadata=true'
	while not terminate_flag:
		loginfo('Starting cryptopanic update')
		try:
			result = requests.get(url).json()
			for r in result['results']:
				if terminate_flag:
					return
				try:
					if 'metadata' not in r or 'description' not in r['metadata']:
						continue
					
					# Prepare data for checking
					data = {
						'title': r['title'],
						'link': r['url']
					}

					# Check if this url already exists in the database
					with dbpool as conn:
						if check_existing_rss_news_item(conn, data['link'], data['title']):
							continue

					# Populate the remaining data fields
					data.update({
						'published': r['published_at'],
						'summary': '',
						'content': '',
						'description': r['metadata']['description'],
						'source': r['source']['domain']
					})

					article = data['source'] + '\n' + data['title'] + '\n' + data['description']
					process_article(article, data)
				except Exception as e:
					loginfo('! inner check_cryptopanic exception')
					loginfo(e)
		except Exception as e:
			loginfo('! check_cryptopanic exception')
			loginfo(e)

		loginfo('Done cryptopanic update')
		sleptfor = 0
		while (not terminate_flag) and sleptfor < 60:
			time.sleep(1)
			sleptfor += 1
	return


def check_feeds():
	global PROMPT_TEMPLATE
	start = time.time()

	loginfo('## Starting rss update')

	for feed_url in rss_feeds:
		if terminate_flag:
			return
		loginfo('>> FEED: ' + feed_url)
		try:
			feed = feedparser.parse(feed_url)
		except Exception as e:
			loginfo(f"Failed to fetch or parse the RSS feed at {feed_url}. Error: {e}")
			continue

		for entry in feed.entries:
			if terminate_flag:
				return
			try:
					# Prepare data for checking
					data = {
						'title': entry.title,
						'link': entry.link
					}

					# Check if this entry already exists in the database
					with dbpool as conn:
						if check_existing_rss_news_item(conn, data['link'], data['title']):
							continue

					# Parse the published date
					published_date = parse(entry.published)

					# Clean the description field
					soup = BeautifulSoup(entry.description, features="html.parser")
					description_text = soup.get_text()

					# Clean the content field
					try:
						content_json = json.dumps(entry.content)
					except Exception as e:
						#loginfo(f"Failed to convert entry.content to JSON for news item {entry.title}. Error: {e}")
						content_json = ""
					soup = BeautifulSoup(content_json, features="html.parser")
					content_text = soup.get_text()

					article = 'Published: ' + entry.published + '\n' + entry.title + '\n' + entry.summary + '\n' + description_text + '\n' + content_text
					data.update({
						'published': published_date,
						'summary': entry.summary,
						'content': content_text,
						'description': description_text,
						'source': feed_url
					})
					process_article(article, data)
			except Exception as e:
					loginfo(f"An error occurred while processing news item {entry.link}. Error: {e}")

	loginfo('!! Done RSS update !!')
	loginfo('Completed in', round(time.time() - start, 1), 's')




def signal_handler(sig, frame):
	global terminate_flag

	loginfo("Received termination signal. Terminating the thread gracefully...")
	terminate_flag = True
	ws_server.terminate_flag=True
	stop_server()

def main():
	global terminate_flag	
	# Register signal handler for SIGINT (Ctrl+C)
	signal.signal(signal.SIGINT, signal_handler)

	#check_feeds()
	schedule.every(10).minutes.do(check_feeds)

	# Start the thread
	my_thread = threading.Thread(target=check_cryptopanic)
	my_thread.start()

	try:
		# Your main program logic here
		while not terminate_flag:
			schedule.run_pending()
			time.sleep(1)
	#except KeyboardInterrupt:
	except Exception as e:
		logerror(e)
		pass
	finally:
		# Wait for the thread to finish before exiting the program
		loginfo('Attempting to join thread')
		my_thread.join(timeout=15)  # Wait for 5 seconds at most
		if my_thread.is_alive():
			loginfo("Thread did not terminate in time. Force quitting.")
		else:
			loginfo("Program exit.")
		#loginfo("Program exit.")

if __name__ == "__main__":
	main()