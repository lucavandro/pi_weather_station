#!/usr/bin/python
# -*- coding: utf-8 -*-

'''
    Stazione Meteo
    di Matteo Coppola

    Questo progetto utilizza la Raspberry Pi e il Sense HAT per raccogliere dati metereologici
    (temperatura, presisone, umidità e immagini dalla webcam) da inviare al sito
    Weather Underground (https://www.wunderground.com)
'''

import time
import logging
from datetime import datetime, timedelta
import os
import sys
import json
import socket
from ftplib import FTP
from threading import Thread
import requests

from sense_hat import SenseHat, ACTION_PRESSED

from config import Config
from icons import Icon


class WeatherStation(object):
    '''
    Modella la stazione metereologica e ne implementa le funzioni principali
    '''

    # URL Weather Underground usato per caricare i dati
    WU_URL = "http://weatherstation.wunderground.com/weatherstation/updateweatherstation.php"
    WP_API_ENDPOINT = "http://api.wunderground.com/api/{api_key}/forecast/q/pws:{station_id}.json"
    #Contiene le ultime 3 temperature lette
    last3_temperatures = []

    # Gli ultimi valori raccolti per temperatura, pressione e umidità
    temp = None
    humidity = None
    pressure = None

    # timestamp
    latest_data_collection = None
    latest_data_upload = None
    latest_picture_upload = None
    latest_icon_update = None

    sense = SenseHat()
    forecast_icon = Icon.SUN

    is_connected = False
    threads = {}

    def __init__(self):
        """
        Effettua il setup della stazione all'avvio
        """

        # Configuro il logging
        logging.basicConfig(
            filename='station.log',
            level=logging.INFO,
            format='%(asctime)s %(message)s')

        self.is_running = True
        print "Station started"
        logging.info("Station started")

        #Imposta la rotazione iniziale dello schermo
        self.sense.rotation = 180

        # Visualizza il messaggio di benvenuto
        self.sense.show_message(
            Config.WELCOME_MESSAGE,
            text_colour=[255, 255, 0],
            back_colour=[0, 0, 255]
        )
        # Gestisce l'input proveniente dal joystick
        self.threads['joystick'] = Thread(target=self.joystick_handler)
        self.threads['joystick'].start()

        # Avvia il controllo ciclico della connessione ad internet
        self.threads['connection'] = Thread(target=self.check_connection)
        self.threads['connection'].is_deamon = True
        self.threads['connection'].start()

        # Resetta lo schermo
        self.sense.clear()

        # Raccoglie i dati
        self.collect_data()

    def joystick_handler(self):
        """
        Alla pressione del joystick aumenta la rotazione di 90 gradi
        """
        while self.is_running:
            event = self.sense.stick.wait_for_event()
            if event.action == ACTION_PRESSED:
                self.sense.rotation = (self.sense.rotation + 90) % 360


    def c_to_f(self, input_temp):
        """
        Converte la temperatura dal Celsius a Fahrenheit
        """
        return (input_temp * 1.8) + 32


    def get_cpu_temp(self):
        """
        'Preso in prestito' da https://www.raspberrypi.org/forums/viewtopic.php?f=104&t=111457
        Chiede al sistema operativo di leggere la temperatura della CPU
        """
        res = os.popen('vcgencmd measure_temp').readline()
        return float(res.replace("temp=", "").replace("'C\n", ""))

    def get_smooth(self, temp):
        """
        Calcola la media delle ultime 3 temperature lette
        """
        # Se non è stata fatta ancora nessuna lettura
        if not self.last3_temperatures:
            # Le ultime tre temperature lette sono uguali e impostate ad temp
            self.last3_temperatures = [temp, temp, temp]
        else:
            self.last3_temperatures.pop(0)
            self.last3_temperatures.append(temp)

        # Ritorna la media delle ultime 3 temperature lette
        return sum(self.last3_temperatures) / 3

    def get_temp(self):
        """
        Sfortunatamente è improbabile che la temperatura letta dal sense HAT
        sia corretta, per maggiori informazioni consultare
        (https://www.raspberrypi.org/forums/viewtopic.php?f=104&t=111457)
        Per qusto motivo è necessario fare una stima della temperatura
        reale tenendo presente la temperatura della CPU. La Pi Foundation
        raccomanda il seguente metodo:
        http://yaab-arduino.blogspot.co.uk/2016/08/accurate-temperature-reading-sensehat.html
        """
        # Leggiamo la temperatura da entrambi i sensori
        temp1 = self.sense.get_temperature_from_humidity()
        temp2 = self.sense.get_temperature_from_pressure()
        # Facciamo la media delle due temperature lette
        avg_temp = (temp1 + temp2) / 2
        # Leggiamo la temperatura della CPU
        cpu_temp = self.get_cpu_temp()
        # Facciamo una stima della temperatura corrente compensando
        # l'influenza della CPU su questo dato
        corr_temp = avg_temp - ((cpu_temp - avg_temp) / 1.5)
        # ritorniamo la media delle ultime 3 temperature lette
        return self.get_smooth(corr_temp)

    def take_picture(self):
        """
        Scatta un immagine dalla webcam
        utilizzando fswebcam (https://github.com/fsphil/fswebcam)
        """
        resolution = Config.PICTURE_RESOLUTION

        # Comando per lo scatto di un immagine
        cmd = "fswebcam -r %s ./pictures/latest.jpg> /dev/null 2>&1"%(resolution)
        print "Acquisita nuova foto"
        # Eseguo il comando
        result = os.system(cmd)
        if result != 0:
            logging.error("Error while taking picture. Error n. " + result)

        # Se è impostata la configurazione prevede il salvataggio
        # di tutte le foto scattate dalla webcam...
        if Config.PRESERVE_OLD_PICTURES:
            # ...creo una copia della foto appena scattata
            filename = datetime.now().strftime('%Y-%m-%dT%H:%M:%S.jpg')
            cmd = "cp ./pictures/latest.jpg %s%s"%(Config.OLD_PICTURES_PATH, filename)
            os.system(cmd)

    def upload_picture(self):
        """
        Invia un immagine scattata dalla webcam tramite FTP
        """
        self.latest_picture_upload = datetime.now()
        ftp = FTP(Config.FTP_SERVER, Config.FTP_LOGIN, Config.FTP_PASSWORD) # Si connette
        try:
            # Imposta il file da inviare, apriamo uno stream per il file
            with open('./pictures/latest.jpg', 'rb') as webcam_picture:
                #di default siamo nella cartella root del sito / -
                # se vogliamo spostarci in un'altra directory è sufficiente scrivere:
                # ftp.cwd('directory')
                ftp.storbinary('STOR image.jpg', webcam_picture) # Invia il file
                webcam_picture.close() # Chiude lo stream del file
                ftp.quit() # Chiude la connessione
        except Exception, e:
            logging.error(e, exc_info=True)


    def collect_data(self):
        """
        Legge dal Sense HAT temperatura, umidità e pressione
        """
        calc_temp = self.get_temp()
        # Arrotonda il valore della temperatura
        self.temp = round(calc_temp, 1)
        self.humidity = round(self.sense.get_humidity(), 0)
        # converte la pressione da millibar a inHg
        self.pressure = round(self.sense.get_pressure() * 0.0295300, 1)
        # Aggiorno il record per l'ultimo dato registrato
        self.latest_data_collection = datetime.now()


    def update_forecast_icon(self):
        """
        Aggiorna l'icona mostrata sul display
        """
        url = self.WP_API_ENDPOINT.format(api_key=Config.API_KEY, station_id=Config.STATION_ID)
        response = requests.get(url)
        json_data = json.loads(response.text)
        icon_name = json_data["forecast"]["simpleforecast"]["forecastday"][0]["icon"]

        if any(word in icon_name for word in ("flurries", "snow")):
            forecast_icon = Icon.SNOW
        elif any(word in icon_name for word in ("rain", "storm")):
            forecast_icon = Icon.RAIN
        elif any(word in icon_name for word in ("cloudy", "hazy", "mostlycloud", "partlysunny")):
            forecast_icon = Icon.CLOUDY_NIGHT if "nt_" in icon_name else Icon.CLOUDY_SUN
        elif any(word in icon_name for word in ("clear", "sunny")):
            forecast_icon = Icon.MOON if "nt_" in icon_name else Icon.SUN
        elif "sleet" in icon_name:
            forecast_icon = Icon.SLEET
        elif "fog" in icon_name:
            forecast_icon = Icon.FOG
        else:
            forecast_icon = Icon.SUN
        self.forecast_icon = forecast_icon
        self.sense.load_image(forecast_icon)

    def upload_data(self):
        """
        Invia i dati raccolti a Undeground weather
        """
        self.latest_data_upload = datetime.now()
        weather_data = {
            "action": "updateraw",
            "ID": Config.STATION_ID,
            "PASSWORD": Config.STATION_KEY,
            "dateutc": "now",
            "tempf": str(self.c_to_f(self.temp)),
            "humidity": str(self.humidity),
            "baromin": str(self.pressure),
        }

        try:
            response = requests.get(self.WU_URL, params=weather_data)
            if response.text == "success":
                logging.info("Data uploaded successfully")
            else:
                logging.error(response.text)
        except Exception as e:
            logging.error(e, exc_info=True)

    def check_connection(self, host="8.8.8.8", port=53, timeout=5):
        """
        Controllo della connessione con ping al DNS di google
        Host: 8.8.8.8 (google-public-dns-a.google.com)
        OpenPort: 53/tcp
        Service: domain (DNS/TCP)
        """
        while self.is_running:
            try:
                socket.setdefaulttimeout(timeout)
                socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect((host, port))
                self.is_connected = True
            except Exception, e:
                self.is_connected = False
                logging.error(e, exc_info=True)

            if self.is_connected:
                time.sleep(60)

    def print_data(self):
        """
        Stampa i dati nel terminale, nel file di log e sullo schermo
        """

        message = "Temp: %sC, Pressione: %shPa, Umidita': %s%%"%(
            self.temp,
            round(self.pressure * 33.86389), #Converto la pressione da inHg a hPa
            self.humidity
        )
        print message
        logging.info(message)
        self.sense.show_message(
            message
        )
        self.sense.load_image(self.forecast_icon)

    def run(self):
        """
        Aggiorna ciclicamente i dati
        """
        while True:
            now = datetime.now()
            # SE non ho mai raccolto dati OPPURE se è scaduto l'intervallo di misurazione
            # ALLORA leggi i dati dai sensori
            if self.latest_data_collection is None or \
            (now - self.latest_data_collection) > timedelta(minutes=Config.MEASUREMENT_INTERVAL):
                self.collect_data()
                self.print_data()


            if self.is_connected:
                # SE non ho mai aggiornato l'icona sul display
                # OPPURE l'ho aggiornata troppo tempo fa
                # ALLORA aggiorna l'icona
                if self.latest_icon_update is None or \
                (now - self.latest_icon_update) > timedelta(minutes=Config.ICON_UPDATE_INTERVAL):
                    if not self.threads.has_key('update_forecast_icon') is None:
                        self.threads['update_forecast_icon'] = Thread(target=self.update_forecast_icon)

                        if not self.threads['update_forecast_icon'].isAlive():
                            self.threads['update_forecast_icon'].start()

                # SE non ho mai inviato dati al sito OPPURE li ho inviati troppo tempo fa
                # ALLORA invia i dati
                if Config.WEATHER_UPLOAD and \
                (self.latest_data_upload is None or \
                (now - self.latest_data_upload) > timedelta(minutes=Config.DATA_UPLOAD_INTERVAL)):
                    if not self.threads.has_key('upload_data') is None:
                        self.threads['upload_data'] = Thread(target=self.upload_data)

                        if not self.threads['upload_data'].isAlive():
                            self.threads['upload_data'].start()

                # SE la webcam è abilitata e non ho mai inviato immagini al sito
                # OPPURE le ho inviate troppo tempo fa
                # ALLORA invia l'immagine
                if Config.WEBCAM_ENABLED and \
                (self.latest_picture_upload is None or \
                (now - self.latest_picture_upload) > timedelta(minutes=Config.PICTURE_UPLOAD_INTERVAL)):
                    if not self.threads.has_key('upload_picture') is None:
                        self.threads['upload_picture'] = Thread(target=self.upload_picture)

                        if not self.threads['upload_picture'].isAlive():
                            self.threads['upload_picture'].start()
            else:
                self.sense.show_message(
                    "Connessione internet assente",
                    text_colour=[255, 0, 0],
                    back_colour=[0, 0, 255]
                )

            time.sleep(
                min(
                    Config.MEASUREMENT_INTERVAL,
                    Config.ICON_UPDATE_INTERVAL,
                    Config.DATA_UPLOAD_INTERVAL,
                    Config.PICTURE_UPLOAD_INTERVAL
                ) * 60
            )

    def stop(self):
        """
        Termina tutti i thread aperti
        """
        print "Stopping station"
        for thread_name, thread in self.threads.iteritems():
            if thread.isAlive():
                thread.join(1)
                print "Thread", thread_name, "stopped."
        logging.info("Station stopped")

if __name__ == "__main__":
    ws = WeatherStation()
    try:
        ws.run()
    except KeyboardInterrupt:
        ws.stop()
        print "\nExiting application\n"
        logging.info("Exiting application")
        sys.exit(0)
