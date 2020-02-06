''' PyQtGraph extensions. '''

from pyqtgraph.Qt import QtGui, QtCore
from pyqtgraph.ptime import time as pgtime
from pyqtgraph.parametertree import Parameter, ParameterTree, registerParameterType, ParameterItem
from pyqtgraph.parametertree.parameterTypes import WidgetParameterItem
import pyqtgraph as pg

class ChannelParameterItem(WidgetParameterItem):
    '''Channel parameters are extended float values displaying plot color as well.'''

    def __init__(self, param, depth):
        WidgetParameterItem.__init__(self, param, depth)
        layout = self.layoutWidget.layout()
        if depth == 1:
            # color defaults to red if not set in opts
            color = param.opts['color'] if 'color' in param.opts else (255,0,0,255)
            self.colorBtn = pg.ColorButton(self.treeWidget(), color)
            layout.insertWidget(0, self.colorBtn)
            self.colorBtn.clicked.disconnect()
            self.colorBtn.clicked.connect(self.colorChange)
            self.colorBtn.setMaximumWidth(30)

    def colorChange(self):
        pass # todo: color adjustment support

    def makeWidget(self):
        '''Extended SimpleParameter widget - float values only, additionally displaying 
        corresponding channel's color.

        Returns:
            widget with a color button and a spinbox for setting threshold value
        '''

        opts = self.param.opts
        t = opts['type']

        defs = {
            'value': 0, 'min': None, 'max': None,
            'step': 1.0, 'dec': False,
            'siPrefix': False, 'suffix': '', 'decimals': 3,
        }
        for k in defs:
            if k in opts:
                defs[k] = opts[k]
        if 'limits' in opts:
            defs['bounds'] = opts['limits']
        w = pg.SpinBox()
        w.setOpts(**defs)
        w.sigChanged = w.sigValueChanged
        w.sigChanging = w.sigValueChanging

        return w

class ChannelParameter(Parameter):
    '''The parameter setup entries for channels are created using this class and
    the underlying :class:`ChannelParameterItem`.
    '''

    itemClass = ChannelParameterItem

    def __init__(self, *args, **kargs):
        Parameter.__init__(self, *args, **kargs)


class DisabledMouseViewBox(pg.ViewBox):
    '''Mouse is disabled in histogram plots using this pg viewbox.'''
    def __init__(self, *args, **kwds):
        pg.ViewBox.__init__(self, *args, **kwds)
        self.setMouseEnabled(False, False)
        #self.setMouseMode(self.RectMode)        

        
registerParameterType('channel', ChannelParameter, override=True)
