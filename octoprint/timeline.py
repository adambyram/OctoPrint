__author__ = 'adambyram'

import logging
import os
import threading
import urllib
import time
import subprocess
import fnmatch
import datetime
import sys
import base64
import PIL
from PIL import Image

import octoprint.util as util

from octoprint.settings import settings
from octoprint.events import eventManager

from apiclient.discovery import build
from oauth2client import client
import httplib2

class Timeline(object):
	def __init__(self, printer):
		self._logger = logging.getLogger(__name__)
		self._clientId = settings().get(["googleApi", "clientId"])
		self._clientSecret = settings().get(["googleApi", "clientSecret"])
		self._accessToken = settings().get(["googleApi", "accessToken"])
		self._idToken = settings().get(["googleApi", "idToken"])
		self._refreshToken = settings().get(["googleApi", "refreshToken"])
		self._logger.debug("Timeline initialized")
		self._credentials = client.OAuth2Credentials(self._accessToken, self._clientId, self._clientSecret, self._refreshToken, 3600, "https://accounts.google.com/o/oauth2/token", "OctoPrint")
		self._http = httplib2.Http()
		# Validation doesn't work for some reason unless running as root - so disable for now
		self._http.disable_ssl_certificate_validation = True
  		self._http = self._credentials.authorize(self._http)
		self._printer = printer
		self._snapshotUrl = settings().get(["webcam", "snapshot"])
		self._currentPercentComplete = 0
		eventManager().subscribe("PrintStarted", self.onPrintStarted)
		eventManager().subscribe("PrintFailed", self.onPrintDone)
		eventManager().subscribe("PrintDone", self.onPrintDone)
		eventManager().subscribe("ZChange", self.onPrintProgress)

	def postToTimeline(self, progressMessage):
		timelineThread = threading.Thread(target=self._timelineWorker, kwargs={"progressMessage": progressMessage})
		timelineThread.daemon = True
		timelineThread.start()

	def unload(self):
		# unsubscribe events
		eventManager().unsubscribe("PrintStarted", self.onPrintStarted)
		eventManager().unsubscribe("PrintFailed", self.onPrintDone)
		eventManager().unsubscribe("PrintDone", self.onPrintDone)
		eventManager().unsubscribe("ZChange", self.onPrintProgress)

	def onPrintStarted(self, event, payload):
		self._currentPercentComplete = 0
		self.postToTimeline("Print Started")

	def onPrintDone(self, event, payload):
		self._currentPercentComplete = 100
		self.postToTimeline("Print Complete")

	def onPrintProgress(self, event, payload):
		progressData = self._printer.getCurrentData()["progress"]
		percentComplete = int(round(progressData["progress"]*100.0))
		percentChangeSinceLastUpdate = percentComplete - self._currentPercentComplete

		if percentChangeSinceLastUpdate >= 10:
			if progressData["printTimeLeft"] is not None:
				self.postToTimeline('{0}% | {1} Remaining'.format(percentComplete,progressData["printTimeLeft"]))
			else:
				self.postToTimeline('{0}% Complete'.format(percentComplete))
			self._currentPercentComplete = percentComplete

	def _timelineWorker(self, progressMessage):
		downloadResult = urllib.urlretrieve(self._snapshotUrl)
		imageFile = downloadResult[0]
		image = Image.open(imageFile)
		imageSize = 640, 360
		image.thumbnail(imageSize,Image.ANTIALIAS)
		image.save(imageFile, format="JPEG")
		with open(imageFile, "rb") as capturedImage:
			imageAsBase64 = urllib.quote_plus(base64.b64encode(capturedImage.read()))

		service = build("mirror", "v1", http=self._http)
		octoPrintLogoData = 'iVBORw0KGgoAAAANSUhEUgAAABQAAAAUCAYAAACNiR0NAAAABmJLR0QA/wD/AP+gvaeTAAAACXBIWXMAAAhOAAAITgGMMQDsAAAAB3RJTUUH3QESEjUTnCnngwAAAl5JREFUOMu91MFrnGUQx/HPPO9uExO20W1SsWougiKCF+3FS9Eawbsg3lQED5b0oOJRvHjSg4nHHsRDT/4JUtPoQSheSg4pCFIllSZxaRXS7G72HQ+72fQgSQRx4IGHeeb5Ms/Mbx7+Y4vDDltXTTRrzyiektrCPdworG2fc/fYwLkfnBzs+QBv40ykEOTBrU6kK5k+6bxo7VDgQ1d9GOlTNPYD6gpFxpCYKImokZY651z8R2B7xbfS+ZG3FoqiG3/pRccgdtBXaZItu/Vp006YMvDTAz1nN16Rpf3d8Hp7xTc4Lwyk1FD0/Fmt2anWtcqmB2NHK/p+jR175Xdz1XVT5ZZ+nvDcvQmXxxm2V7yBy0IdtciG0HWnuq4SWiq/RHg3i2tb77kz96UpoW3g9di1WM+bHzxOdC3sA6/heSGTELqNNbt6ZrJy5VTHwo2P1fDwknJ7cbiH2VWl/OjS4GlvZdulaK96TG0d00iViE13q5tmsqmW5rcWbRylv9mvfF7PWyjS2RFs2L/QL9saWSHd2lq0MffF4XqF7Te9H12fFemJUfRQbT09/aHu8Ojssie3Lh5I8DD741VfF8zUeZ+IBoo9IYb5Rnrt34xegYj7BFlGK8euC6eWTR0fGDZjVD41mqMZOZiKR0rtHTi9dHQtC27m/oNDrTKZ0/pSjrHhoxG9HAksrCfdcT41OWMQKYWCPZyZXfby1qLBkcCq6efgt3GOKfKkiSx21QhVDPt14Vg1vP2CGt+PPYmGKidl1GMP6aXZJXPH6rKwOlJNQlaaJuVwDo1+La3gWf+3/Q03NNjBcIFb6QAAAABJRU5ErkJggg=='
		html = '<article class="photo"><img src="data:image/jpeg;base64,'
		html += imageAsBase64
		html += '" width="100%" height="100%"><div class="photo-overlay"></div><section></section><footer><img class="left icon-small" src="data:image/png;base64,'
		html += urllib.quote_plus(octoPrintLogoData)
		html += '"><p>'
		html += progressMessage
		html += '</p></footer></article>'
		body = {
			'html': html,
			'menuItems': [{'action': 'NAVIGATE'}],
			'notification': {'level': 'DEFAULT'}
    	}
		service.timeline().insert(body=body).execute()