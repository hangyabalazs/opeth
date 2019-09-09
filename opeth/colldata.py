'''Stores the collected raw data, gives functions to perform various things on it. Supported functionality:

* keep only a predefined amount of data (a window of the last n second of samples), dropping old data

* help in quick plotting of raw data (compress it for display)

* search for spikes over threshold

Data, TTL and timestamp storage happens in :class:`Collector` class, and
Spike detection and data compression for raw plotting are performed in :class:`DataProc`.
'''

from __future__ import division
import time
import logging
import  numpy as np
import math
from collections import OrderedDict, deque, defaultdict
#from matplotlib import pyplot as plt
from openephys import generate_ttl
from circbuff import CircularBuffer

EVENT_ROI = (-0.02, 0.05)       #: Region of interest in seconds (+-timestamp range in seconds - neighbourhood of a event that is investigated for spikes)

SAMPLES_PER_SEC = 30000         #: Sampling frequency in Hz

# default threshold level for spike detection
SPIKE_THRESHOLD = 0.5
# holdoff time in seconds (suppress spikes too nearby to each other)
SPIKE_HOLDOFF = 0.00075         #: Dead time / censoring period (seconds)

DBG_TEXT_DUMP = False

if DBG_TEXT_DUMP:
    flog = open('textlog.txt', 'wt')

class Collector(object):
    '''Data storage class for raw analog data, timestamps and event timestamps.
    
    Attributes:
        databuffer (2D CircularBuffer): The 2D data storage, each row representing a channel, each column a sample.
        tsbuffer (1D CircularBuffer): Timestamp buffer storing 1 time stamp value for each data column.
        timestamp: Sample number updated on timestamp event or when received explicitly with a set of data.
        spikes (deque): Spike positions - stored if spikes are sent by OE.
        ttls (deque): TTL positions as sent by OE.
        samples_per_sec (int): Sampling rate.
        prev_trigger_ts (defaultdict(int)): Used to detect backward jumping timestamps in TTL stamps.
        drop_aux (bool): Adjusted through :meth:`set_drop_aux`, affects whether auxiliary data (the
            3 gyroscope channels) is to be filtered or not.
    '''
    
    def __init__(self):
        
        self.timestamp = 0
        
        self.databuffer = None
        self.tsbuffer = None
        
        self.spikes = deque()
        self.ttls = deque()
        self.prev_trigger_ts = defaultdict(int)
        self.starttime = time.clock()

        self.set_sampling_rate(SAMPLES_PER_SEC)

        self.drop_aux = False
        
    def update_ts(self, timestamp):
        '''Required for old OE version that sent timestamps separately as events,
        kept it for backward compatibility.
        
        Args:
            timestamp (int): stored in :attr:`timestamp` for later timestamp interpolation calculations
                when data arrives.
        '''
        self.timestamp = timestamp
        if DBG_TEXT_DUMP: flog.write("Timestamp: %d\n" % self.timestamp)

        now = time.clock()

    def add_data(self, data):
        '''Append a new set of analog channel measurements to the end of the storage array.
        
        Auxiliary channel data (gyroscopes) are automatically removed if 35 or 70 channels 
        were received (ch 33-35 or ch 65-70) and :attr:`drop_aux` is True.
        
        Data sampling timestamps are calculated for each sample position based on the last received
        timestamp (stored in :attr:`timestamp` and the sample rate defaults to :attr:`SAMPLES_PER_SEC`.
        
        Args:
            data: input data received from OE. Multiple channels, multiple samples.
                (E.g. 35 rows/channels of 640 floating point samples.) Unit value is supposed to be in uV.
        '''
    
        # we accept only 2D arrays!
        assert(len(data.shape) == 2)
        
        # we get rid of AUX data (gyroscope) if 35 or 70 channels are present
        if self.drop_aux:
            if data.shape[0] == 35:
                data = data[:32]
            elif data.shape[0] == 70:
                data = data[:64]

        # interpolate timestamps - actually sample index counter
        curr_ts = np.arange(self.timestamp, self.timestamp + data.shape[1], dtype='int64')

        # we start a new collection
        #    * on startup or
        #    * when current time is earlier than earliest stored timestamp (restarted rec)

        if self.databuffer is not None and len(self.databuffer) > 0 and curr_ts[-1] < self.tsbuffer[0]:
            msgstr = "Timestamp jump: %d..%d -> %d..%d" % (self.tsbuffer[0], self.tsbuffer[-1], curr_ts[0], curr_ts[-1])
            logger.debug(msgstr)
            if DBG_TEXT_DUMP:
                flog.write(msgstr + "\n")

        if self.databuffer is None:
            # first run: create circular buffer
            itemcnt = 100000
            shape = list(data.shape)
            shape[1] = itemcnt * 2
            self.databuffer = CircularBuffer(capacity=itemcnt, allocated=itemcnt*2, dtype=np.float32, initial_shape=shape, append_axis=1)
            shape = [itemcnt * 2]
            self.tsbuffer = CircularBuffer(capacity=itemcnt, allocated=itemcnt*2, dtype=np.int64, initial_shape=shape, append_axis=0)
        elif curr_ts[-1] < self.tsbuffer[0]:
            # timestamp jump
            logger.debug("Timestamp jump, dropping everything before")
            self.databuffer.drop(len(self.databuffer))
            self.tsbuffer.drop(len(self.tsbuffer))
        else:
            # normal append
            pass

        self.databuffer.append(data)
        self.tsbuffer.append(curr_ts)

        assert(self.databuffer.shape[1] == self.tsbuffer.shape[0])

        self.drop_before(self.timestamp - self.max_data_amount)

    def drop_before(self, timestamp):
        '''Drop old data which is not required for any of the various displays.
        '''

        if len(self.tsbuffer) > 1:
            amin = np.argmax(self.tsbuffer >= timestamp)
            self.tsbuffer.drop(amin)
            self.databuffer.drop(amin)

        assert(self.databuffer.shape[1] == self.tsbuffer.shape[0])

    
    def keep_last(self, seconds=None, samples=None, **kwargs):
        '''Convenience wrapper function for :attr:`drop_before`.
        
        Args:
            seconds (int): length of samples to be kept in buffer (in number of seconds). If given, it takes precedence over `samples`.
            samples (int): number of samples to be kept in buffer.
        '''
        if self.tsbuffer is None or len(self.tsbuffer) == 0:
            return
        if seconds is not None:
            self.drop_before(self.tsbuffer[-1] - self.samples_per_sec * seconds)
        elif samples is not None:
            self.drop_before(self.tsbuffer[-1] - samples)

    def has_data(self):
        '''
        Returns:
            true if there is (already/still) data in the buffers.'''
        if self.databuffer is None:
            return False
        return len(self.databuffer) > 0

    def get_data(self):
        '''Accessor function for the :attr:`databuffer`. 
        
        Obsolete. Former version could return the proper structure depending on which
        data storage backend was used. Now one may use :attr:`databuffer` directly as no other structure is configurable.
        '''
        return self.databuffer
        
    def get_ts(self):
        '''
        Returns:
            the timestamp buffer :attr:`tsbuffer`.'''
        return self.tsbuffer

    def channel_cnt(self):
        '''
        Returns:
            the number of channels based on the rows of data in the :attr:`databuffer`.
        '''
        if not self.has_data():
            return 0
        else:
            return self.databuffer.shape[0]

    def add_spike(self, spike):
        '''Store a new spike event. (Not used currently.)'''
        self.spikes.append(spike)

    def add_ttl(self, ttl):
        '''Store a new TTL event.
        
        All TTLs are stored regardless of the selected TTL channel, 
        the TTL processing happens in :meth:`process_ttl`.
        This code assumes the timestamp and the sample count are the same.
        '''
        ttl.base_timestamp = self.timestamp
        if ttl.timestamp is None:
            ttl.timestamp = self.timestamp + ttl.sample_num
        self.ttls.append(ttl)
        if DBG_TEXT_DUMP:
            flog.write("TTL: %s\n" % str(ttl))

    def process_ttl(self, start_offset=EVENT_ROI[0], end_offset=EVENT_ROI[1],
                    ttl_ch=None, trigger_holdoff = 0.001, **kwargs):
        '''Process a TTL (event), return data and timestamp around event on success
        or (None, None) otherwise - using first TTL from ttl_ch.
        
        Drops all TTLs silently from channels other than ttl_ch.
        Works on data accumulated by :meth:`add_data` calls (:attr:`dataarray` numpy array) 
        and TTLs from :meth:`add_ttl` calls (self.ttls list). Too frequent pulses are filtered
        by `trigger_holdoff`

        Args:
            start_offset (float): TTL-relative start offset in seconds, typically a small negative value to return data 
                collected right before the TTL signal
            end_offset (float): TTL-relative end offset in seconds specifying end of data ROI
            ttl_ch (int): channel whose TTL events are to be processed as trigger
            trigger_holdoff (float): holdoff time in seconds until no new triggers are processed
                (to protect the system against trigger bursts in case of broken cabling etc.)
        Returns:
            2D numpy array of data (one row per channel) around the TTL ``[-start_offset .. +end_offset]``, 
            1D numpy array of timestamps (same number of columns as data).
            Timestamps are actually sample number (sort of).
        '''

        while 1:
            if len(self.tsbuffer) == 0:
                logger.info("No data to perform operations on")
                return None, None

            if not self.ttls:
                return None, None

            ttl = self.ttls[0]

            if ttl_ch is not None and ttl.event_channel != ttl_ch:
                self.ttls.popleft()
                continue
            elif ttl.timestamp > self.tsbuffer[-1] + self.samples_per_sec * 2:
                # We have a TTL for the proper channel, let's check whether a timestamp jump has occured
                # If ttl timestamp is far in the future (compared to data) we drop it, as it is probably 
                #  a remainder of a previous OE play session
                logger.info("Dropping TTL timestamp ", ttl.timestamp, "- last data ts: ", self.tsbuffer[-1])
                self.ttls.popleft()
                continue
            else:
                pass

            # check for ttl trigger ts
            # If the last timestamp is more than 1 sec ahead, then we had a timestamp jump,
            #  stop using old timeout values
            if self.prev_trigger_ts[ttl_ch] > ttl.timestamp + 1:
                logger.info("Timestamp jump detected during TTL processing")
                for k in self.prev_trigger_ts.keys():
                    self.prev_trigger_ts[k] = 0

            elif self.prev_trigger_ts[ttl_ch] > ttl.timestamp + trigger_holdoff:
                # normal case, previous TTL was too near (within holdoff)
                continue
            else:
                # normal case, new valid TTL detected - keep its timestamp for timeout
                self.prev_trigger_ts[ttl_ch] = ttl.timestamp

            tsrange_min = ttl.timestamp + start_offset * self.timestamp_per_sec
            tsrange_min = max(tsrange_min, 0)
            tsrange_max = ttl.timestamp + end_offset * self.timestamp_per_sec

            #print "For TTL", ttl, ":"
            #print "Checking data in range", tsrange_min, "-", tsrange_max, "data available in range", self.tsbuffer[0], "-", self.tsbuffer[-1]

            if tsrange_min < self.tsbuffer[0]: # corresponding data is already lost, drop this TTL
                logger.info("TTL timestamp %d earlier than available data %d, skipping" % (tsrange_min, self.tsbuffer[0]))
                self.ttls.popleft()
                continue

            if tsrange_max < self.tsbuffer[-1]:
                # the entire region of interest for the TTL is present -> returning the data
                self.ttls.popleft()
                over_or_eq_min = self.tsbuffer >= tsrange_min
                below_or_eq_max = self.tsbuffer <= tsrange_max
                within_limits = np.logical_and(over_or_eq_min, below_or_eq_max)
                data = self.databuffer[:, within_limits]
                ts = self.tsbuffer[within_limits]
                return data, ts
            else:
                return None, None
                
    def set_drop_aux(self, should_drop):
        '''Update AUX channel settings (whether we'd like to search for spikes on them or not).'''
        self.drop_aux = should_drop
        
    def set_sampling_rate(self, sampling_rate):
        self.samples_per_sec = sampling_rate
        self.timestamp_per_sec = sampling_rate # current open ephys report timestamps as sample index
        self.max_data_amount = 2 * self.timestamp_per_sec   #: Buffering limit (sample count)

class DataProc(object):
    '''Utility functions to handle collected data
    '''

    def __init__(self, collector=None, drop_aux = False):
        '''
        Args:
            collector (Collector): data on which the operations are performed. Only a reference, 
                part of data to operate on is passed over to each function.
            drop_aux (bool): sets whether in a 35 or 70 analog channel case is a 32+3 (or 64+6) setup
                with extra 3 (or 6) channels unimportant and to be dropped or important and are to be 
                parsed for spikes.
        '''
            
        self.coll = collector
        self.coll.set_drop_aux(drop_aux)
        
        # initial setup - will be overridden after parameter updates
        self.set_sampling_rate(SAMPLES_PER_SEC)
        
        # AutoTTL is used only in simulation: in case of missing trigger events
        # generate them based on a selected channel's detected spikes.
        #self.autottl_holdoff_value = int(0.04 * SAMPLES_PER_SEC)

        self.autottl_holdoff_until = 0

    def compress(self, data, rate, timestamps=None):
        '''Compress a 2D matrix column-wise by keeping the min and max values of the compressed chunks.
        
        Used by real time raw display to reduce number of points to be plotted.
        The displayed set tries to plot a sawtooth-style signal touching both 
        min and max values of the original signal of the given range.
        
        Args:
            data (2D CircularBuffer): array to be compressed.
            rate (int): required compression rate.
            timestamps (1D CircularBuffer): timestamp axis is compressed the same way as vertical
        ''' 
        # drop first non-full chunk if necessary
        if data.shape[1] % rate != 0:
            data = data[:, -int(data.shape[1]/rate)*rate:]

        # drop timestamps that do not have their data counterpart
        timestamps = timestamps[-data.shape[1]:]

        rows = data.shape[0]
        cols = data.shape[1] // rate

        compressed = np.ndarray((rows,cols * 2), dtype=str(data.dtype))

        # compress also the timestamp - calculate the "mid point" of the timestamp range 
        #  and set that as position for both min and max values
        if timestamps is not None:
            compts = np.ndarray((1, cols*2), dtype=str(timestamps.dtype))
            datats = timestamps.reshape(cols, rate)
            tsmin, tsmax = datats.min(axis=1).reshape(-1,1), datats.max(axis=1).reshape(-1,1)
            tsvals = (tsmin+tsmax) / 2.0
            compts = np.concatenate((tsvals, tsvals), axis=1).ravel()

        for i in range(data.shape[0]):
            drow = data[i]
            dproc = drow.reshape(cols, rate)

            mins, maxes = dproc.min(axis=1).reshape(-1,1), dproc.max(axis=1).reshape(-1,1)
            
            compressed[i, :] = np.concatenate((mins, maxes), axis=1).ravel() # a row of min0, max0, min1, max1... for each "rate" sized data chunk

        if timestamps is None:
            return compressed
        else:
            return compressed, compts

    def spikedetect(self, data, timestamps, threshold = SPIKE_THRESHOLD, rising_edge = False, disabled = []):
        """Detect spikes based on threshold level.

        Spike detection: from first continouos block of data exceeding threshold
        select maximal [minimal in case of negative threshold] value as spike position
        and don't search for spikes in the :attr:`SPIKE_HOLDOFF` time after crossing the threshold level.
        
        Threshold method is selected by :attr:`SPIKE_THRESHOLD_BELOW` setting (True by default).
        
        Args:
            threshold (scalar or vector): must have the same number of channels as data.
            data (ndarray e.g. CircularBuffer): samples on which spike filtering will be performed.
            timestamps: time stamps accompanying the data samples
            rising_edge (bool): false if threshold level should be considered a negative threshold
                and falling edge is to be detected
            
        Returns:
            a list of spike positions (sample index) and another list of the same position as timestamp.
        """

        if rising_edge:
            thresholded = data >= threshold
        else:
            thresholded = data <= threshold

        # simplest spike detection: first index of signal over threshold 
        #where = np.argmax(thresholded, axis = 1) 
        #if type(threshold) != float:
        #    print "T0", threshold, data.min(), data.max()
        #    print "Where:", where
        #    return [], []

        # spike detection is per-channel

        spikepositions = []
        spikestamps = []

        for i in range(data.shape[0]):
            offset = 0  # next search position
            # thresholded bool value for a single channel
            ch_thresholded = thresholded[i,:]

            # list of spike positions on a single channel
            ch_pos, ch_time = [], []

            if i not in disabled:
                while len(ch_thresholded[offset:])>0:

                    # get the index of the first element exceeding threshold
                    first_over = np.argmax(ch_thresholded[offset:])

                    # check whether the return value of argmax is valid
                    # -> exit from inner loop if nothing over threshold limit left
                    if first_over == 0 and ch_thresholded[offset] == False:
                        break

                    first_over += offset
                    next_within = np.argmin(ch_thresholded[first_over:])
                    if next_within == 0:  # end of data, still over threshold
                        next_within = len(ch_thresholded)
                    else:
                        next_within += first_over

                    drange = range(first_over, next_within)

                    if rising_edge:
                        spike_tip_pos = np.argmax(data[i, drange]) + first_over
                    else:
                        spike_tip_pos = np.argmin(data[i, drange]) + first_over
                    ch_pos.append(spike_tip_pos)
                    ch_time.append(timestamps[spike_tip_pos])

                    # Continue processing after current spike
                    # - if spike is 'flat' (too many samples over threshold) then immediately when it's again
                    #   below threshold
                    # - if spike is normal (shorter than spike_holdoff_samples) then not earlier than holdoff
                    #   (measured from first sample where spike is over threshold)
                    offset = max(first_over + self.spike_holdoff_samples, next_within)

            spikepositions.append(ch_pos)
            spikestamps.append(ch_time)

        return spikepositions, spikestamps
        
    def set_sampling_rate(self, sampling_rate):
        logger.info("Data processor assumes sampling rate %d" % sampling_rate)
        self.spike_holdoff_samples = int(round(SPIKE_HOLDOFF * sampling_rate))
        self.autottl_holdoff_value = int(0.04 * sampling_rate)
        
    # ONLY FOR DEBUG / SIMULATION
    def autottl(self, data, timestamps, base_timestamp, ch=0, threshold = SPIKE_THRESHOLD, **kwargs):
        '''Generate TTL signals based on threshold in a channel of data.
        
        Playback from file in OE did not support TTL event playback, so it was necessary to generate
        them somehow.
        
        Not used in real situations.
        
        Args:
            ch: channel to run thresholding on for TTL signals
            threshold: threshold level
            base_timestamp: TTL timestamp relative to start of data packet timestamp (in samples)
                Probably unnecessary, just kept for emulating OE TTL data.
        '''
        
        valid_data = data[ch:ch+1, timestamps > self.autottl_holdoff_until]
        valid_ts = timestamps[timestamps > self.autottl_holdoff_until]
        
        if len(valid_ts) == 0:
            return None

        spikepos, spikestamps = self.spikedetect(valid_data, valid_ts, threshold)
 
        ttl_event = None
        if spikepos and spikepos[0]:
            ttlts = spikestamps[0][0]
            ttl_event = generate_ttl(ttlts, ttlts - base_timestamp)
            self.autottl_holdoff_until = ttlts + self.autottl_holdoff_value


        return ttl_event

logger = logging.getLogger("logger") 
