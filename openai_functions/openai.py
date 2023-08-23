import tiktoken
import openai
from openai import ChatCompletion
import os
import time
from dotenv import load_dotenv
load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")

def num_tokens_from_text(text, model="gpt-3.5-turbo-0301"):
	messages = [
		{
				"role": "user",
				"content": text,
		}
	]
	"""Returns the number of tokens used by a list of messages."""
	try:
			encoding = tiktoken.encoding_for_model(model)
	except KeyError:
			encoding = tiktoken.get_encoding("cl100k_base")
	if model == "gpt-3.5-turbo-0301":  # note: future models may deviate from this
			num_tokens = 0
			for message in messages:
				num_tokens += 4  # every message follows <im_start>{role/name}\n{content}<im_end>\n
				for key, value in message.items():
					num_tokens += len(encoding.encode(value))
					if key == "name":  # if there's a name, the role is omitted
							num_tokens += -1  # role is always required and always 1 token
			num_tokens += 2  # every reply is primed with <im_start>assistant
			return num_tokens
	else:
			raise NotImplementedError(f"""num_tokens_from_messages() is not presently implemented for model {model}.
	See https://github.com/openai/openai-python/blob/main/chatml.md for information on how messages are converted to tokens.""")


# this can be either used with text alone, or with text that needs to be inserted into a prompt before num tokens is calculated
def trim_text_to_token_limit(text, max_tokens, target_tokens, tolerance=0.05, prompt=None, insertion_key=None):
	# Initial bounds for binary search
	lower_bound = 0
	if prompt:
		this_text = prompt.replace(insertion_key, text)
	else:
		this_text = text
	upper_bound = len(this_text)

	# Perform binary search to find the approximate cutoff point
	while lower_bound < upper_bound:
		# Get the middle point of the current bounds
		mid = (lower_bound + upper_bound) // 2

		# Estimate the token count based on the provided function
		if prompt:
			this_text_truncated = prompt.replace(insertion_key, text[:mid])
		else:
			this_text_truncated = text[:mid]
		current_tokens = num_tokens_from_text(this_text_truncated)
		#print(max_tokens, current_tokens)

		# Check if the current token count is within the tolerance
		if target_tokens * (1 - tolerance) <= current_tokens <= max_tokens:
			return text[:mid]

		# Adjust the bounds based on the current token count
		if current_tokens < target_tokens * (1 - tolerance):
			lower_bound = mid + 1
		else:
			upper_bound = mid - 1

	# If the loop doesn't return early, return the closest possible approximation
	return text[:lower_bound]

def do_chat_completion(prompt_template, text, insertion_key, completion_tokens, max_tries=5):
	prompt = prompt_template.replace(insertion_key, text)
	success = False
	tries = 0
	
	completion_tokens = 800
	n_tokens = num_tokens_from_text(prompt)
	# This model's maximum context length is 16385 tokens
	if n_tokens+completion_tokens > 16300:
		truncated_article = trim_text_to_token_limit(text, 16340-completion_tokens, 16340-completion_tokens, tolerance=0.05, prompt=prompt_template, insertion_key=insertion_key)
		prompt = prompt_template.replace(insertion_key, truncated_article)
		model = "gpt-3.5-turbo-16k"
	elif n_tokens+completion_tokens > 4050:
		model = "gpt-3.5-turbo-16k"
	else:
		model="gpt-3.5-turbo-0613"

	while not success and tries < max_tries:
		try:
			response = ChatCompletion.create(
				model=model,
				temperature=0,
				max_tokens=800,
				request_timeout=60,
				messages=[
								{
										"role": "user",
										"content": prompt,
								}
				]
			)
			success = True
			response_content = response.choices[0].message.content			
			time.sleep(5)
			return response_content
		except Exception as e:
			print(e)
			# 16k model error:
			# This model's maximum context length is 16385 tokens
			if e.user_message.startswith("This model's maximum context length is 4097 tokens"):
					model = "gpt-3.5-turbo-16k"
			else:
					print('.')
					time.sleep(10)
			tries += 1
	return None