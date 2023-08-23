DROP TABLE IF EXISTS rss_news_sentiment;
DROP TABLE IF EXISTS rss_news_items;

CREATE TABLE rss_news_items (
    id SERIAL PRIMARY KEY,
    title VARCHAR(255),
    link VARCHAR(500) UNIQUE,
    published TIMESTAMP,
    summary TEXT,
    content TEXT,
	 description TEXT
);

CREATE TABLE rss_news_sentiment (
    id SERIAL PRIMARY KEY,
    crypto_type VARCHAR(255) NOT NULL,
    crypto_name VARCHAR(255) NOT NULL,
    symbol VARCHAR(255),
    org_name VARCHAR(255),
    sentiment_score REAL NOT NULL,
    movement_score REAL NOT NULL,
    indicator_certainty REAL NOT NULL,
	 sentiment_timestamp TIMESTAMP,
	 best_match_cmc_id VARCHAR(10),
	 best_match_cmc_name VARCHAR(255),
	 best_match_cmc_match_score FLOAT,
	 best_match_coinpaprika_id VARCHAR(255),
	 best_match_coinpaprika_match_score FLOAT,
    newsitem_id INTEGER REFERENCES rss_news_items(id)
);