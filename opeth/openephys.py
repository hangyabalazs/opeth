import numpy as np

class OpenEphysEvent(object):
    '''Open Ephys events generic container for e.g. timestamps or TTLs.
    
    Notes: New version of OE does not seem to send timestamp events.
        OE-detected spikes are stored in the more specific `OpenEphysSpikeEvent` class.
    
    Mostly based on Francesco Battaglia's code.
    '''
    event_types = {0: 'TIMESTAMP', 1: 'BUFFER_SIZE', 2: 'PARAMETER_CHANGE',
                   3: 'TTL', 4: 'SPIKE', 5: 'MESSAGE', 6: 'BINARY_MSG'}

    def __init__(self, _d, _data=None):
        '''
        Args:
            _d: json-extracted dictionary with which to initialize the object
            _data: binary content of the rest of the message (e.g. undecoded timestamp as received)
        '''
        self.type = None
        self.event_id = 0
        self.sample_num = 0
        self.event_channel = 0
        self.numBytes = 0
        self.data = b''
        self.timestamp = None
        self.__dict__.update(_d)
        # noinspection PyTypeChecker
        self.type = OpenEphysEvent.event_types[self.type]
        if _data:
            self.data = _data
            self.numBytes = len(_data)

        if self.type == 'TIMESTAMP':
            t = np.frombuffer(self.data, dtype=np.int64)
            self.timestamp = t[0]

    #def set_data(self, _data):   
    #    self.data = _data
    #    self.numBytes = len(_data)

    def __str__(self):
        ds = self.__dict__.copy()
        del ds['data']
        return str(ds)


class OpenEphysSpikeEvent(object):
    '''Storage class for spike events received from OE.
    '''
    def __init__(self, _d, _data=None):
        self.n_channels = 0
        self.n_samples = 0
        self.pc_proj = []
        self.gain = []
        self.electrode_id = 0
        self.timestamp = 0
        self.channel = 0
        self.threshold = []
        self.color = []
        self.source = 0
        self.__dict__.update(_d)
        self.data = _data

    def __str__(self):
        ds = self.__dict__.copy()
        del ds['data']
        return str(ds)

def generate_ttl(timestamp, sample_num = 0):
    ''' Debug code to auto-generate TTLs based on threshold level in case of file playback. '''

    #{'event_channel': 0, 'event_id': 1, u'timestamp': 519170, 'base_timestamp': 518912, 'numBytes': 8, 'type': 'TTL', 'sample_num': 258}
    e_template = {"type": 3, "timestamp": timestamp, "event_id": 1,
        "base_timestamp": timestamp - sample_num, "sample_num": sample_num, "numBytes": 0}
    return OpenEphysEvent(e_template)
