import time
import logging
import numpy as np

from pyqtgraph.Qt import QtGui, QtCore
import pyqtgraph as pg
from pyqtgraph.parametertree import Parameter, ParameterTree

class SpikeEvalGui(object):
    '''Spike evaluation plots for a given channel.
    
    Three main areas: top part is a full timeline plot displaying the original 
    signal with the detected spikes overlayed in different color, and the 
    bottom part is a per-spike grid of plots displaying the detected spikes
    individually. On the right side parameters can be adjusted.
    '''

    NOF_SPIKEPLOTS = 9      #: Bottom spike window grid settings
    NOF_SPIKEPLOTS_PER_ROW = 3 #: Bottom spike window grid settings
    MAX_PLOT_PER_SEC = 5    #: Continuous spike window refresh rate (if "Update only on spike" not selected)
    PENWIDTH = 2            #: Plot draw width
    
    SPIKE_ROI_BEFORE = 0.0003 #: Bottom display limit: in seconds before peak of spike
    SPIKE_ROI_AFTER  = 0.001  #: Bottom display limit: in seconds after peak of spike

    # colors from http://colorbrewer2.org/#type=qualitative&scheme=Paired&n=9
    COLORS = ['1f78b4', 'b2df8a', '33a02c', 'fb9a99', 'e31a1c', 'fdbf6f', 'ff7f00', 'cab2d6', 'a6cee3']

    def __init__(self, sample_rate):
        ''' GUI initialization
        
        Attributes:
            spikeplotpool (list): List of plots in the grid (not used)
            spikeplotcurves (list): Spike waveforms in :attr:`spikeplotpool` used for setData
            spikeplotpositions (list): Marker for the detected threshold crossing
            spikerawcurves (list):  Curves to overlay the top display with the color of specific spikes
            spikeplotpool_next (int): Index of current spike in the given round of plots 
                (for color and plot window cycling)
        '''
        self.spikewin = QtGui.QWidget()
        self.spikewin.setWindowTitle("Spike window")
        vbox = QtGui.QVBoxLayout(self.spikewin)

        splitter_horiz = QtGui.QSplitter(QtCore.Qt.Horizontal)
        splitter_vert = QtGui.QSplitter(QtCore.Qt.Vertical)

        self.spikeplotwidget_raw = pg.PlotWidget(title="Raw data")
        self.spikeplot = self.spikeplotwidget_raw.plot([0], [0], 
                                    pen=pg.mkPen(width=self.PENWIDTH), antialias=True)
        self.spikeplot_thresh = self.spikeplotwidget_raw.plot([0], [0], 
                                    pen=pg.mkPen(width=self.PENWIDTH), antialias=False)
        self.spikeplotwidget_raw.setLabel('bottom', "offset from trigger", units='s')
        self.spikeplotwidget_raw.setLabel('left', "Signal level", units='V')

        splitter_vert.addWidget(self.spikeplotwidget_raw)

        self.spikeplotwidget_spikes = pg.GraphicsLayoutWidget()

        self.spikeplotpool = []
        self.spikeplotcurves = []
        self.spikeplotpositions = []
        self.spikerawcurves = []
        self.spikeplotpool_next = 0

        self.sample_rate = sample_rate

        for i in range(self.NOF_SPIKEPLOTS):
            plt = self.spikeplotwidget_spikes.addPlot(title="spike #%d" % (i+1))
            plt.setLabel('left', units='V')
            plt.setLabel('bottom', units='s')
            self.spikeplotpool.append(plt)

            self.spikeplotcurves.append(self.spikeplotpool[-1].plot([0],[0]))
            self.spikeplotpositions.append(self.spikeplotpool[-1].plot([0],[0], symbolBrush=(255,0,0), symbolPen='w'))
            self.spikerawcurves.append(self.spikeplotwidget_raw.plot([0],[0]))
            if (i + 1) % self.NOF_SPIKEPLOTS_PER_ROW == 0:
                self.spikeplotwidget_spikes.nextRow()

        splitter_vert.addWidget(self.spikeplotwidget_spikes)
        splitter_vert.setStretchFactor(10,1)
        splitter_vert.setSizes([10,20])

        # right side control panel
        splitter_horiz.addWidget(splitter_vert)
        rightside = QtGui.QWidget()
        l = QtGui.QVBoxLayout(rightside)
        rightside.setLayout(l)

        # window parameters in control panel
        l.addWidget(QtGui.QLabel("Control Panel"))

        self.splitparams = Parameter.create(name='splitparams', type='group')
        self.par_channel = Parameter.create(name='Channel', type='int', limits=(1,40))
        self.par_update_on_spikes = Parameter.create(name='Update only on spikes', type='bool', value=True)
        self.splitparams.addChild(self.par_channel)
        self.splitparams.addChild(self.par_update_on_spikes)
        t = ParameterTree()
        t.setParameters(self.splitparams, showTop=False)
        l.addWidget(t)

        splitter_horiz.addWidget(rightside)

        vbox.addWidget(splitter_horiz)
        self.spikewin.setLayout(vbox)
        self.spikewin.show()
        logger.info("Spike win created")

        # other local variables
        self.earliest_plot = time.clock()   #: timestamp until new plot is created to limit update frequency 

    def plot(self, data_ts, data, spike_ts, spike_pos, threshold_levels):
        '''Plot a set of data and corresponding spikes on the selected channel.
        
        Args:
            data_ts: timestamps
            data: data to plot - only the selected channel will be plotted
            spike_ts: timestamps where spikes were detected by :meth:`colldata.DataProc.spikedetect`.
            spike_pos: spike positions as detected by :meth:`colldata.DataProc.spikedetect`.
            threshold_levels: per channel threshold level for plotting
        '''
        
        if self.earliest_plot > time.clock():
            #print "Prevented too frequent plotting"
            return

        # convert data to volts scale from uV
        data = data / 1000000.0
        ch = self.par_channel.value() - 1
        always_update = not self.par_update_on_spikes.value()

        if not always_update and len(spike_pos[ch]) == 0:
            return

        self.spikeplot.setData(data_ts, data[ch])
        threshold_levels = threshold_levels / 1000000.0

        # horizontal line for trigger threshold display
        dts = np.array([data_ts[0], data_ts[-1]])
        thres = np.array([threshold_levels[ch][0],threshold_levels[ch][0]])
        self.spikeplot_thresh.setData(dts, thres)

        # individual spikes - clear all first
        self.spikeplotpool_next = 0
        for c in self.spikeplotcurves:
            c.setData([0], [0])
        for c in self.spikerawcurves:
            c.setData([0], [0])
            
        # determine position limits based on sampling rate
        pos_before = int(self.sample_rate * self.SPIKE_ROI_BEFORE)
        pos_after =int(self.sample_rate * self.SPIKE_ROI_AFTER)

        for ts, pos in zip(spike_ts[ch], spike_pos[ch]):
            plotrange = slice(pos - pos_before, pos + pos_after)

            self.spikeplotpositions[self.spikeplotpool_next].setData([data_ts[pos]], [data[ch][pos]])
            self.spikeplotcurves[self.spikeplotpool_next].setData(data_ts[plotrange], data[ch][plotrange],
                    pen=pg.mkPen(color=self.COLORS[self.spikeplotpool_next], width=self.PENWIDTH, antialias=True))
            self.spikerawcurves[self.spikeplotpool_next].setData(data_ts[plotrange], data[ch][plotrange],
                    pen=pg.mkPen(color=self.COLORS[self.spikeplotpool_next], width=self.PENWIDTH, antialias=True))
            self.spikeplotpool_next = (self.spikeplotpool_next + 1) % len(self.spikeplotpool)

        self.earliest_plot = time.clock() + 1.0 / self.MAX_PLOT_PER_SEC

    def close(self):
        '''Called when main window is closed.'''
        self.spikewin.close()

logger = logging.getLogger("logger")
