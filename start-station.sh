#!/bin/bash

# How To Autostart Apps In Rasbian LXDE Desktop
# http://www.raspberrypi-spy.co.uk/2014/05/how-to-autostart-apps-in-rasbian-lxde-desktop/

echo "Starting Weather Station"

if [ ! -d "/home/pi/pi_weather_station/pictures" ]; then
  # Control will enter here if $DIRECTORY doesn't exist.
  mkdir /home/pi/pi_weather_station/pictures
fi

/usr/bin/python /home/pi/pi_weather_station/weather_station.py