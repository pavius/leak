# Leak

Monitors OpenSprinkler and:
1. Messages you on Telegram if a leak is detected 
2. Periodically emails you a PDF report with stats you can show your friends and bask in their indifference

# Using

> Note: Builds for Docker/your favorite CRI on Raspberry Pi (armhf) only. Change the Dockerfile or run in a virtualenv anywhere else

Build it:
```sh
make
```

Send it to your favorite rpi:
```sh
docker save leak:latest -o leak
scp leak pi@<whatever>:/home/pi/leak

sudo docker load -i leak (on the rpi)
```

Create a configuration file (use etc/leak.yaml.template as a starting point) and run it:
```sh
sudo docker run -v $(pwd)/leak.yaml:/leak/leak.yaml leak
```
