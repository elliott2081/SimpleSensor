"""
Websocket server communication module
"""

from websocket_server import WebsocketServer
from simplesensor.shared.threadsafeLogger import ThreadsafeLogger
from simplesensor.shared.message import Message
from simplesensor.shared.moduleProcess import ModuleProcess
from distutils.version import LooseVersion, StrictVersion
from .version import __version__
from . import moduleConfigLoader as configLoader
from threading import Thread
import sys
import json
import time

class WebsocketServerModule(ModuleProcess):
    def __init__(self, baseConfig, pInBoundQueue, pOutBoundQueue, loggingQueue):

        # super(WebsocketServerModule, self).__init__()
        ModuleProcess.__init__(self, baseConfig, pInBoundQueue, pOutBoundQueue, loggingQueue)
        self.alive = False
        self.config = baseConfig
        self.inQueue = pInBoundQueue  # inQueue are messages from the main process to websocket clients
        self.outQueue = pOutBoundQueue  # outQueue are messages from clients to main process
        self.websocketServer = None
        self.loggingQueue = loggingQueue
        self.threadProcessQueue = None

        # Configs
        self.moduleConfig = configLoader.load(self.loggingQueue, __name__)

        # Constants
        self._port = self.moduleConfig['WebsocketPort']
        self._host = self.moduleConfig['WebsocketHost']

        # logging setup
        self.logger = ThreadsafeLogger(loggingQueue, __name__)

    def run(self):
        if not self.check_ss_version():
            #cant run with wrong version so we return early
            return False
        
        """ Main thread entry point.

        Sets up websocket server and event callbacks.
        Starts thread to monitor inbound message queue.
        """

        self.logger.info("Starting websocket server")
        self.alive = True
        self.listen()

        self.websocketServer = WebsocketServer(self._port, host=self._host)
        self.websocketServer.set_fn_new_client(self.new_websocket_client)
        self.websocketServer.set_fn_message_received(self.websocket_message_received)
        self.websocketServer.run_forever()

    def check_ss_version(self):
        #check for min version met
        self.logger.info('Module version %s' %(__version__))
        if LooseVersion(self.config['ss_version']) < LooseVersion(self.moduleConfig['MinSimpleSensorVersion']):
            self.logger.error('This module requires a min SimpleSensor %s version.  This instance is running version %s' %(self.moduleConfig['MinSimpleSensorVersion'],self.config['ss_version']))
            return False
        return True

    def new_websocket_client(self, client, server):
        """ Client joined callback - called whenever a new client joins. """

        self.logger.debug("Client joined")

    def websocket_message_received(self, client, server, message):
        """ Message received callback - called whenever a new message is received. """

        self.logger.debug('Message received: %s'%message)
        message = json.loads(message)
        self.logger.info("message jsond: %s"%message)
        _msg = Message(
            topic=message['topic'], 
            sender_id=message['sender_id']
            )
        if 'sender_type' in message: 
            _msg.sender_type=message['sender_type']
        if 'recipients' in message: 
            _msg.recipients=message['recipients']
        if 'extended_data' in message: 
            _msg.extended_data=message['extended_data']
            
        self.put_message(_msg)

    def listen(self):
        self.threadProcessQueue = Thread(target=self.process_queue)
        self.threadProcessQueue.setDaemon(True)
        self.threadProcessQueue.start()

    def shutdown(self):
        """ Handle shutdown message. 
        Close and shutdown websocket server.
        Join queue processing thread.
        """

        self.logger.info("Shutting down websocket server")

        try:
            self.logger.info("Closing websocket")
            self.websocketServer.server_close()
        except Exception as e:
            self.logger.error("Websocket close error : %s " %e)

        try:
            self.logger.info("Shutdown websocket")
            self.websocketServer.shutdown()
        except Exception as e:
            self.logger.error("Websocket shutdown error : %s " %e)

        self.alive = False
        
        self.threadProcessQueue.join()

        time.sleep(1)
        self.exit = True

    def handle_message(self, message):
        """ Send message to listening clients. """
        self.websocketServer.send_message_to_all(json.dumps(message.__dict__))

    def process_queue(self):
        """ Monitor queue of messages from main process to this thread. """

        while self.alive:
            if (self.inQueue.empty() == False):
                try:
                    message = self.inQueue.get(block=False,timeout=1)
                    if message is not None:
                        if message.topic.upper() == "SHUTDOWN":
                            self.logger.debug("SHUTDOWN handled")
                            self.shutdown()
                        else:
                            self.handle_message(message)
                except Exception as e:
                    self.logger.error("Websocket unable to read queue : %s " %e)
            else:
                time.sleep(.25)
