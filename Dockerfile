FROM balenalib/raspberry-pi-debian-python:3.7.4

RUN apt-get update \
    && apt-get install -y git build-essential libatlas-base-dev libjpeg62-turbo libopenjp2-7 libtiff5 libxcb-xinput0 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /leak

COPY requirements.txt ./
RUN echo '[global]\nextra-index-url=https://www.piwheels.org/simple' > /etc/pip.conf
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD [ "python", "./main.py", "--config-path", "/leak/leak.yaml" ]
