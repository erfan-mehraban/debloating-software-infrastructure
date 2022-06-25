FROM python:2.7
RUN pip install flask redis

RUN apt-get update && apt-get install -y redis-server \
	&& rm -rf /var/lib/apt/lists/*

ADD app.py /code/app.py
WORKDIR /code

CMD redis-server & python app.py

