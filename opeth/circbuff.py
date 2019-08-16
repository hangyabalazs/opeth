import logging
import numpy as np
from collections import Sequence

class CircularBuffer(Sequence):
    """Ring buffer implementation with continuous memory storage.
    
    Appends/expands happen along specified axis.
    
    The data is always stored continuously in the memory in a numpy array
    targeted for quick "bulk" read access. As the elements get inserted at end 
    and read/released from the beginning the actual buffer slowly reaches the end 
    of the allocated space, when it needs to be moved to the start of the 
    allocated space to keep it continuous. Inserts are supported at the end only,
    data removals ("drop data") only at the beginning of the array.
    
    Array in memory is not from ``[0..len(arr))``, instead from some offset: 
    ``[self._left_index .. self._right_index)``, where ``self._right_index <= self._allocated`` and
    ``self._right_index - self._left_index <= self._capacity``.
    
    Was tested for OE purposes only, other usage patterns may bring unexpected errors.
    """

    def __init__(self, capacity, allocated, initial_shape, dtype=np.float64, append_axis=0, **kwargs):
        """
        Args:
            capacity (int): Max num of rows/cols along `append_axis` to be stored in the circular buffer.
            allocated (int): Actual storage area for storing the continuous ring buffer.
                Bigger allocated storage results in less data moves but more memory consumption.
                Must be greater than `capacity` (depends on usage patterns).
            initial_shape (list(row,col,..)): full array size to be allocated. Size must match allocated
                in the `append_axis` direction.
            dtype (type): data type to be stored
            append_axis (int): axis in which direction data is appended to the already stored data.
        
        Raises:
            ValueError: triggered if appends are not row/columnwise (``axis > 1``) - others were not tested yet
        """
        if append_axis > 1:
            raise ValueError("Unexpected append axis, currently 0 and 1 is supported")
        
        assert(allocated >= capacity)
        
        self._arr = np.zeros(initial_shape, dtype)
        self._append_axis = append_axis
        assert(self._arr.shape[self._append_axis] == allocated)
        
        self._capacity = capacity
        self._allocated = allocated
        self._left_index = 0
        self._right_index = 0 # next write position
        
    def append(self, value):
        """Insert an item at the end of the array.
        
        Not an O(1) operation in case the new items would span over the end of the allocated space:
        in this case the array contents are moved to the start of the allocated space first.
        
        Args:
            value (dtype as specified during instantiation): an array of values with the
                expected shape (all dimensions must match `initial_shape`'s dimensions except the
                dimension of `append_axis`).
                
        Raises:
            BufferError: if number of items in array would be over capacity limit after the append
        """
        
        appendcnt = value.shape[self._append_axis]
        if len(self) + appendcnt > self._capacity:
            raise BufferError("Append: ring buffer is full, cap: %d, result would be: %d+%d = %d" %
                (self._capacity, len(self), appendcnt, len(self) + appendcnt))
        
        # todo: support arbitrary axes, not only the first two
        # todo: support non-numpy appends as well
        elemcnt = value.shape[self._append_axis]
        
        if self._right_index + elemcnt > self._arr.shape[self._append_axis]:
            # time to make place for the new elements first
            if self._append_axis == 0:
                self._arr[0:self._right_index - self._left_index] = self._arr[self._left_index:self._right_index]
            elif self._append_axis == 1:
                self._arr[:, 0:self._right_index - self._left_index] = self._arr[:, self._left_index:self._right_index]
            
            self._right_index -= self._left_index
            self._left_index = 0
        
        # add in the new elements
        if self._append_axis == 0:
            self._arr[self._right_index:self._right_index+elemcnt] = value
        elif self._append_axis == 1:
            self._arr[:, self._right_index:self._right_index+elemcnt] = value
        self._right_index += elemcnt
        
    def drop(self, nof_elements):
        """Remove elements from the beginning of the array.
        
        Args:
            nof_elements (int): number of rows/cols/... along append_axis that should 
                be removed from the start of the array.
                
        Raises:
            BufferError: if more elements are attempted to be released than present.
        """
        if len(self) >= nof_elements:
            self._left_index += nof_elements
        else:
            raise BufferError("Attempt to drop %d items but only %d present" % (nof_elements, len(self)))
    
    def _adjust_index(self, idx, leftid, rightid):
        """
        Change input array indexing to match the offseted indexes caused by the displaced array.
        When attempting to read elements from the array along the append-axis, 0:-1 is 
        actually left_index:right_index - adjust all indices accordingly.
        
        Raises:
            IndexError: index exceeds available data
        """
        if idx < 0:
            # reverse indexed
            upd = idx + self._right_index
        else:
            # normal indexing
            upd = idx + self._left_index
        if upd < self._left_index or upd >= self._right_index:
            raise IndexError("Invalid index received: %d modified to %d on axis %d" % 
                                (idx, upd, self._append_axis))
        else:
            return upd

    def size(self):
        """Return capacity of array: as set in constructor. Available data count is accessible through len(),
        free size is cb.size() - len(cb)."""
        return self._capacity
            
    ## Sequence methods follow...
    def __getitem__(self, item):
        """Return an item or an array, supporting various numpy operations
        
        Override append axis item positions for the growing direction
        (In `append_axis` direction item 0 is actually at `_left_index` in the actual array `_arr`)
        
        Raises:
            IndexError: index exceeds available data.
        """
        
        # shortcut for ndarray accessors - sub-optimal
        if isinstance(item, np.ndarray) and (item.dtype == np.bool):
            return self[:][item]
        
        items_refined =  item
        if not isinstance(item, tuple):
            items_refined = [item]
        else:
            items_refined = list(item)
            
        while 1:
            if len(self._arr.shape) <= len(items_refined):
                break
            items_refined.append(slice(None, None, None))

            # all multidimensional arrays will be handled through tuples for simplicity - extend everything to tuples
            
        # now that all values are set, let's add offset along the
        # growing/circular buffer axis direction with _left_index and _right_index
        upd = items_refined[self._append_axis]

        if type(upd) == int:
            upd_idx = self._adjust_index(upd, self._left_index, self._right_index)
            items_refined[self._append_axis] = upd_idx
        elif isinstance(upd, slice):
            # a slice has 3 items: start, stop, step - rebuild a new one with corrected indexes
            slice_start = self._left_index if upd.start is None else self._adjust_index(upd.start, self._left_index, self._right_index)
            slice_stop = self._right_index if upd.stop is None else self._adjust_index(upd.stop, self._left_index, self._right_index)
            items_refined[self._append_axis] = slice(slice_start, slice_stop, upd.step)
        elif isinstance(upd, np.ndarray):
            if upd.dtype != np.bool:
                items_refined[self._append_axis] = upd + self._left_index
            else: # hack: handle the case when the input array is a bool mask
                return self[:][tuple(items_refined)]
        elif type(upd) == list:
            # todo: support negative indices
            items_refined[self._append_axis] = np.array(upd) + self._left_index
            
        return self._arr[tuple(items_refined)]

    def __setitem__(self, item, value):
        """Set a single item. 
        
        This is a very rudmentary single-item only implentation yet!
        May trigger exceptions or unexpected behaviour if used for other purposes.
        """
        item_refined = list(item)
        item_refined[self._append_axis] = item[self._append_axis] + self._left_index
        self._arr[item] = value
        
    def __len__(self):
        """Length: number of array items along `append_axis`."""
        return self._right_index - self._left_index
        
    def __str__(self):
        return "<ContinuousRingBuffer: \n" + str(self[:]) + "\n>"

    def min(self):
        """Return the minimum value."""
        return np.min(self[:])

    def max(self):
        """Return the maximum value."""
        return np.max(self[:])

    '''
    Comparisons
    '''
    
    def __lt__(self, other):
        return self[:] < other
    
    def __le__(self, other):
        return self[:] <= other
        
    def __gt__(self, other):
        return self[:] > other
        
    def __ge__(self, other):
        return self[:] >= other
        
    def __cmp__(self, other):
        if self.__lt__(other):
            return -1
        elif self.__gt__(other):
            return 1
        else:
            return 0
        
    def __eq__(self, other):
        return self[:] == other
        
    def __ne__(self, other):
        return self[:] != other
        
    @property
    def dtype(self):
        """Returns the data type for the array items"""
        return self._arr.dtype

    @property
    def shape(self):
        """Returns the shape of the array currently stored. In a freshly created array
        all dimensions except the append_axis will report the `initial_shape`; the 
        `append_axis` will report 0 as no items (rows, cols) available yet.
        
        The array used for storing data is 0..allocated in the `append_axis` direction,
        but the shape returns only the rows/cols currently available in that direction
        """
        
        container_shape = list(self._arr.shape)
        container_shape[self._append_axis] = len(self)
        return tuple(container_shape)
    
if __name__ == "__main__":
    #data = np.ones([64,10], dtype='float32')
    #print data.shape

    #cb = ContinuousRingBuffer(capacity=10, allocated=20, initial_shape=[64,20], dtype=np.float32, append_axis = 1)
    #cb.append(data)
    
    cb = ContinuousRingBuffer(capacity=50, allocated=100, initial_shape=[3,100], dtype=np.float32, append_axis = 1)

    '''
    for i in [1,3,2,4,5,1]:
        data = np.ones([3,i])*i
        
        cb.append(data)
    
    cb[0]                           # 0
    cb[0:10,3]                      # (slice(0, 10, None), 3)
    cb[3,4]                         # (3, 4)
    cb[:]
    cb[np.array([1,2,5]),10]        # (array([1, 2, 5]), 10)
    cb[:, 3]
    cb[1:3]
    cb[:, -5:]
    '''
    
    print("empty:", cb[0])
    cb.append(np.ones([3, 1]) * 1)
    cb.append(np.ones([3, 1]) * 2)
    cb.append(np.ones([3, 1]) * 3)
    print("then:", cb[:, :])
    cb.drop(1)
    print("drop:", cb[0, :])

logging.getLogger("logger") 