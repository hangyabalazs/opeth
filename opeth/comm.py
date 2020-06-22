'''Communication interface between Open Ephys and Python using ZeroMQ for networking and JSON message format.

Sends periodic heartbeat signals to the server, uses :class:`collector.Collector`
to store data received over network.

Heavily based on Francesco Battaglia's sample implementation.
'''
from __future__ import print_function
import sys
from timeit import default_timer

import time
import logging
import zmq
import numpy as np
import uuid
import json

from .openephys import OpenEphysEvent, OpenEphysSpikeEvent
from .colldata import Collector, SAMPLES_PER_SEC

COMMPROCESS_MAX_POLLTIME = 0.1    # max amount of time that can be spent in the communication loop before returning

class CommProcess(object):
    '''ZMQ communication process - stores data, called periodically from GUI process.
    
    Attributes:
        context (zmq.Context): Networking context for ZeroMQ
        dataport (int): TCP port of Open Ephys plugin for data reception
        eventport (int): TCP port of Open Ephys plugin for events
        data_socket (zmq.SUB socket): ZMQ subscriber for incoming data
        event_socket (zmq.SUB socket): ZMQ REQ interface
    '''
    
    def __init__(self, dataport=5556, eventport=5557):
        '''
        Attributes:
            collector (:class:`collector.Collector`): Data storage
            
        Args:
            dataport (int): Open Ephys ZMQ plugin's data port, default: 5556
            eventport (int): Open Ephys ZMQ plugin's event port, default: 5557            
        '''
        self.context = zmq.Context()
        self.dataport = dataport
        self.eventport = eventport
        self.data_socket = None
        self.event_socket = None
        self.poller = zmq.Poller()
        self.message_no = -1
        self.socket_waits_reply = False
        self.event_no = 0
        self.app_name = 'Plot Process'
        self.uuid = str(uuid.uuid4())   #: unique ID used in heartbeat 
        self.last_heartbeat_time = 0
        self.last_reply_time = time.time()
        self.isTesting = False
        self.isStats = False
        self.msgstat_start = None
        self.msgstat_size = []
        self.collector = Collector()
        
        self.samprate = -1
        self.channels = 0

        logger.debug("ZMQ: dataport %d, eventport %d" % (dataport, eventport))

    def add_data(self, n_arr):
        '''Append data to our data `collector`.'''
        self.collector.add_data(n_arr,)

    def add_event(self, event):
        '''Add/update event or timestamp.'''
        if event.type == 'TIMESTAMP':
            self.collector.update_ts(event.timestamp)
        elif event.type == 'TTL' and event.event_id == 1: # rising edge TTL
            self.collector.add_ttl(event)

    def adjust_samprate(self, samprate):
        ''' When a new sampling rate is detected in the data, we alert the upper layers '''
        if samprate != self.samprate:
            logger.info("Sampling rate changed: %d -> %d" % (self.samprate, samprate))
            self.samprate = samprate
            self.collector.update_samprate(samprate)
            
    def adjust_channels(self, channels):
        if channels != self.channels:
            logger.info("Channel count changed: %d -> %d" % (self.channels, channels))
            self.channels = channels
            self.collector.update_channels(channels)
            
    # noinspection PyMethodMayBeStatic
    def add_spike(self, spike):
        '''Add spikes. Currently not used.'''
        logger.info("Spike detected...")
        logger.info(spike)
        self.collector.add_spike(spike)

    def send_heartbeat(self):
        '''Send heartbeat message to the event port so the ZMQ plugin can list our client.'''
        d = {'application': self.app_name, 'uuid': self.uuid, 'type': 'heartbeat'}
        j_msg = json.dumps(d)
        logger.info("sending heartbeat")
        self.event_socket.send(j_msg.encode('utf-8'))
        self.last_heartbeat_time = time.time()
        self.socket_waits_reply = True

    def send_event(self, event_list=None, event_type=3, sample_num=0, event_id=2, event_channel=1):
        '''
        Note: 
            Not used just for testing.'''
        if not self.socket_waits_reply:
            self.event_no += 1
            if event_list:
                for e in event_list:
                    self.send_event(event_type=e['event_type'], sample_num=e['sample_num'], event_id=e['event_id'],
                                    event_channel=e['event_channel'])
            else:
                de = {'type': event_type, 'sample_num': sample_num, 'event_id': event_id % 2 + 1,
                      'event_channel': event_channel}
                d = {'application': self.app_name, 'uuid': self.uuid, 'type': 'event', 'event': de}
                j_msg = json.dumps(d)
                #print(j_msg)
                if self.socket_waits_reply:
                    logger.error("Can't send event")
                else:
                    self.event_socket.send(j_msg.encode('utf-8'), 0)
            self.socket_waits_reply = True
            self.last_reply_time = time.time()
        else:
            logger.info("can't send event, still waiting for previous reply")

    def connect(self):
        '''Initial connection to ZMQ plugin.
        
        Starts polling the interfaces.'''
        logger.info("init socket")
        self.data_socket = self.context.socket(zmq.SUB)
        self.data_socket.connect("tcp://localhost:%d" % self.dataport)

        self.event_socket = self.context.socket(zmq.REQ)
        self.event_socket.connect("tcp://localhost:%d" % self.eventport)

        self.data_socket.setsockopt(zmq.SUBSCRIBE, b'')
        self.poller.register(self.data_socket, zmq.POLLIN)
        self.poller.register(self.event_socket, zmq.POLLIN)

    def timer_callback(self):
        '''Called periodically from GUI to process network messages.
        
        All the most important network processing happens here.
        
        * Sends heartbeat messages every two seconds.
        * Collects data.
        * Processes incoming events.
        '''
        events = []

        if not self.data_socket:
            self.connect()

        if self.isTesting:
            if np.random.random() < 0.005:
                self.send_event(event_type=3, sample_num=0, event_id=self.event_no, event_channel=1)

        start = default_timer()
        timeout = start + COMMPROCESS_MAX_POLLTIME   # spend maximum this amount of time in the loop

        while default_timer() < timeout:
            if (time.time() - self.last_heartbeat_time) > 2.:

                # Send every two seconds a "heartbeat" so that Open Ephys knows we're alive
                # and also check for response
                if self.socket_waits_reply:
                    logger.error("No reply to heartbeat, retrying... (Don't panic. :) )")
                    self.last_heartbeat_time += 1.
                    if (time.time() - self.last_reply_time) > 10.:
                        # reconnecting the socket as per the "lazy pirate" pattern (see the ZeroMQ guide)
                        logger.warning("Looks like we lost the server, trying to reconnect")
                        self.poller.unregister(self.event_socket)
                        self.event_socket.close()
                        self.event_socket = self.context.socket(zmq.REQ)
                        self.event_socket.connect("tcp://localhost:%d" % self.eventport)
                        self.poller.register(self.event_socket, zmq.POLLIN)
                        self.socket_waits_reply = False
                        self.last_reply_time = time.time()
                else:
                    self.send_heartbeat()

            socks = dict(self.poller.poll(1))
            if not socks:
                break

            # process incoming data
            if self.data_socket in socks:

                try:
                    message = self.data_socket.recv_multipart(zmq.NOBLOCK)
                except zmq.ZMQError as err:
                    logger.error("Got error: {0}".format(err))
                    break

                if message:
                    if len(message) < 2:
                        logger.info("No frames for message: ", message[0])
                    try:
                        header = json.loads(message[1].decode('utf-8'))
                    except ValueError as e:
                        logger.error("ValueError: ", e)
                        logger.info(message[1])

                    if self.isStats: # statistics
                        if self.msgstat_start is None:
                            self.msgstat_start = default_timer()

                        self.msgstat_size.append(len(message[1]))

                        if self.msgstat_start + 1 < default_timer():
                            logger.debug(len(self.msgstat_size))
                            sizes, counts = np.unique(self.msgstat_size, return_counts=True)
                            logger.debug(sizes, counts)
                            logger.debug(sum(counts), "messages", sum(self.msgstat_size), "bytes")
                            self.msgstat_size = []
                            self.msgstat_start = default_timer()

                    if self.message_no != -1 and header['message_no'] != self.message_no + 1:
                        logger.error("Missing a message at number %d", self.message_no)
                    self.message_no = header['message_no']
                    if header['type'] == 'data':
                        c = header['content']
                        n_samples = c['n_samples']
                        n_channels = c['n_channels']
                        self.adjust_channels(n_channels)
                        n_real_samples = c['n_real_samples']
                        
                        if 'sample_rate' in c:
                            self.adjust_samprate(c['sample_rate'])
                        else:
                            # use defaults if old protocol messages were used
                            self.adjust_samprate(SAMPLES_PER_SEC)

                        # new version of the ZMQ plugin: data packets contain timestamps as well
                        if 'timestamp' in c:
                            timestamp = c['timestamp']
                            # this is a hack to make the TTL timestamps match the data timestamps
                            self.collector.update_ts(timestamp + n_real_samples)

                        try:
                            n_arr = np.frombuffer(message[2], dtype=np.float32)
                            n_arr = np.reshape(n_arr, (n_channels, n_samples))
                            #print (n_channels, n_samples)
                            if n_real_samples > 0:
                                n_arr = n_arr[:, 0:n_real_samples]
                                self.add_data(n_arr)
                                
                        except IndexError as e:
                            logger.error(e)
                            logger.error(header)
                            logger.error(message[1])
                            if len(message) > 2:
                                logger.error(len(message[2]))
                            else:
                                logger.error("Only one frame???")

                    elif header['type'] == 'event':
                        if header['data_size'] > 0:
                            event = OpenEphysEvent(header['content'], message[2])
                        else:
                            event = OpenEphysEvent(header['content'])
                        self.add_event(event)
                    elif header['type'] == 'spike':
                        spike = OpenEphysSpikeEvent(header['spike'], message[2])
                        self.add_spike(spike)

                    elif header['type'] == 'param':
                        c = header['content']
                        self.__dict__.update(c)
                        print(c)
                    else:
                        raise ValueError("message type unknown")

                else:
                    logger.info("No data received")

                    break
            elif self.event_socket in socks and self.socket_waits_reply:
                message = self.event_socket.recv()
                #logger.info("Event reply received")
                logger.info(message.decode('utf-8'))
                if self.socket_waits_reply:
                    self.socket_waits_reply = False
                else:
                    logger.info("???? Getting a reply before a send?")
        if events:
            pass  # TODO implement the event passing

        if timeout < default_timer():
            logger.info("Abort due to timeout")

        return True

logger = logging.getLogger("logger")
