from collections import defaultdict
from timeit import default_timer

class TimeMeasClass(object):
    '''Performance monitoring/profiling class. (Just for development.)

    Maintains a dictionary of elapsed times and number of calls with separate identifier strings
    to make it possible to measure multiple overlapping time segments.
    '''

    def __init__(self):
        self.timespent = defaultdict(int) #: Measurement array for elapsed time
        self.timestart = defaultdict(int) #: Last measurement's start time (initialized in :meth:`tic`)
        self.timecount = defaultdict(int) #: Number of measurements collected in :attr:`timespent` (for averaging)

    def tic(self, idstr):
        '''Start timer.

        Arguments:
            idstr (str): Starts timer for given string id. Will be terminated by :meth:`toc`.
        '''
        self.timestart[idstr] = default_timer()

    def toc(self, idstr):
        '''Stop timer, increment corresponding timer arrays.

        Arguments:
            idstr (str): Index string of :attr:`timespent` and :attr:`timecount`.

        Returns:
            elapsed time since last tic in seconds
        '''
        delta = default_timer() - self.timestart[idstr]
        self.timespent[idstr] += delta
        self.timecount[idstr] += 1
        return delta

    def dump(self, logger):
        '''Display all timer results.'''
        for i in sorted(self.timestart.keys()):
            logger.debug("%15s: %f / %d" % (str(i), self.timespent[i], self.timecount[i]))

    def reset(self):
        '''Restart all timers.'''
        for i in sorted(self.timestart.keys()):
            self.timespent[i] = 0
            self.timecount[i] = 0


