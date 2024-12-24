FROM xbltb/document-reader-mini

MAINTAINER Bashkirtsev D.A. <bashkirtsevich@gmail.com>
LABEL maintainer="bashkirtsevich@gmail.com"

RUN apt-get -y install mc \
    && apt-get install poppler-utils \
    && apt-get -y install libimage-exiftool-perl

COPY . /app

WORKDIR /app

RUN pip install --upgrade pip \
    && pip install -r requirements.txt

ENV RABBIT_URL amqp://guest:guest@localhost

CMD python app.py
