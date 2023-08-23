# RSS Crypto News Sentiment Analysis V1
This is a version of our crypto sentiment pipeline which matches tokens to news articles and provides sentiment data based on news articles. We found this method to be incomplete, and have started work to train a model specifically for sentiment analysis for crypto news - with awareness of hype/shilling.

However, if someone is trying to build something similar. This is potentially a good jumping off point.

You will need to write code for  update_cmc_coinpaprika_matches.py to get matched tokens, as our API is not part of the open source release.

## License
See License.md. This code is MIT Licensed. 


To run this application you need python3 and the following requirements.

pip3 install feedparser sqlalchemy transformers schedule psycopg2-binary

## AI API
This version has been changed to use OpenAI instead of our fine-tuned LLAMA2 based LLM, you will need to put an OpenAI key in your env file under OPENAI_API_KEY to use this. This should provide similar results to our local LLM.

## Support
The Software and related documentation are provided “AS IS” and without any warranty of any kind and Seller EXPRESSLY DISCLAIMS ALL WARRANTIES, EXPRESS OR IMPLIED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE.

Octavia Labs 

Last Code Change - June 2023