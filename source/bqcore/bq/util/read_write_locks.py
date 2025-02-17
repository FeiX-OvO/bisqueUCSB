"""read_write_locks.py - Read-Write thread lock implementation
Name-based hash for read/write locks

Copyright (C) 2008, Center for Bio Image Informatcs
"""

##########################################################################
# read/write locking
##########################################################################
#
#import threading
#
# class ReadWriteLock:
#    """ A lock object that allows many simultaneous "read locks", but
#    only one "write lock." """
#
#    def __init__(self):
#        self._read_ready = threading.Condition(threading.Lock(  ))
#        self._readers = 0
#        self._writers = 0
#
#    def acquire_read(self):
#        """ Acquire a read lock. Blocks only if a thread has
#        acquired the write lock. """
#        self._read_ready.acquire(  )
#        try:
#            self._readers += 1
#        finally:
#            self._read_ready.release(  )
#
#    def release_read(self):
#        """ Release a read lock. """
#        self._read_ready.acquire(  )
#        try:
#            self._readers -= 1
#            if not self._readers:
#                self._read_ready.notifyAll(  )
#        finally:
#            self._read_ready.release(  )
#
#    def acquire_write(self):
#        """ Acquire a write lock. Blocks until there are no
#        acquired read or write locks. """
#        self._read_ready.acquire(  )
#        self._writers += 1
#        while self._readers > 0:
#            self._read_ready.wait(  )
#
#    def release_write(self):
#        """ Release a write lock. """
#        self._writers -= 1
#        self._read_ready.release(  )


##########################################################################
# read/write locking
##########################################################################

"""locks.py - Read-Write lock thread lock implementation

See the class documentation for more info.

Copyright (C) 2007, Heiko Wundram.
Released under the BSD-license.
"""

from threading import Condition, Lock, currentThread
from time import time


class ReadWriteLock(object):
    """Read-Write lock class. A read-write lock differs from a standard
    threading.RLock() by allowing multiple threads to simultaneously hold a
    read lock, while allowing only a single thread to hold a write lock at the
    same point of time.

    When a read lock is requested while a write lock is held, the reader
    is blocked; when a write lock is requested while another write lock is
    held or there are read locks, the writer is blocked.

    Writers are always preferred by this implementation: if there are blocked
    threads waiting for a write lock, current readers may request more read
    locks (which they eventually should free, as they starve the waiting
    writers otherwise), but a new thread requesting a read lock will not
    be granted one, and block. This might mean starvation for readers if
    two writer threads interweave their calls to acquireWrite() without
    leaving a window only for readers.

    In case a current reader requests a write lock, this can and will be
    satisfied without giving up the read locks first, but, only one thread
    may perform this kind of lock upgrade, as a deadlock would otherwise
    occur. After the write lock has been granted, the thread will hold a
    full write lock, and not be downgraded after the upgrading call to
    acquireWrite() has been match by a corresponding release().
    """

    def __init__(self):
        """Initialize this read-write lock."""

        # Condition variable, used to signal waiters of a change in object
        # state.
        self.__condition = Condition(Lock())

        # Initialize with no writers.
        self.__writer = None
        self.__upgradewritercount = 0
        self.__pendingwriters = []
        self.__writercount = 0

        # Initialize with no readers.
        self.__readers = {}

    def acquire_read(self, timeout=None):
        """Acquire a read lock for the current thread, waiting at most
        timeout seconds or doing a non-blocking check in case timeout is <= 0.

        In case timeout is None, the call to acquireRead blocks until the
        lock request can be serviced.

        In case the timeout expires before the lock could be serviced, a
        RuntimeError is thrown."""

        if timeout is not None:
            endtime = time() + timeout
        me = currentThread()
        self.__condition.acquire()
        try:
            if self.__writer is me:
                # If we are the writer, grant a new read lock, always.
                self.__writercount += 1
                return
            while True:
                if self.__writer is None:
                    # Only test anything if there is no current writer.
                    if self.__upgradewritercount or self.__pendingwriters:
                        if me in self.__readers:
                            # Only grant a read lock if we already have one
                            # in case writers are waiting for their turn.
                            # This means that writers can't easily get starved
                            # (but see below, readers can).
                            self.__readers[me] += 1
                            return
                        # No, we aren't a reader (yet), wait for our turn.
                    else:
                        # Grant a new read lock, always, in case there are
                        # no pending writers (and no writer).
                        self.__readers[me] = self.__readers.get(me, 0) + 1
                        return
                if timeout is not None:
                    remaining = endtime - time()
                    if remaining <= 0:
                        # Timeout has expired, signal caller of this.
                        raise RuntimeError("Acquiring read lock timed out")
                    self.__condition.wait(remaining)
                else:
                    self.__condition.wait()
        finally:
            self.__condition.release()

    def acquire_write(self, timeout=None):
        """Acquire a write lock for the current thread, waiting at most
        timeout seconds or doing a non-blocking check in case timeout is <= 0.

        In case the write lock cannot be serviced due to the deadlock
        condition mentioned above, a ValueError is raised.

        In case timeout is None, the call to acquireWrite blocks until the
        lock request can be serviced.

        In case the timeout expires before the lock could be serviced, a
        RuntimeError is thrown."""

        if timeout is not None:
            endtime = time() + timeout
        me, upgradewriter = currentThread(), False
        self.__condition.acquire()
        try:
            if self.__writer is me:
                # If we are the writer, grant a new write lock, always.
                self.__writercount += 1
                return
            elif me in self.__readers:
                # If we are a reader, no need to add us to pendingwriters,
                # we get the upgradewriter slot.
                if self.__upgradewritercount:
                    # If we are a reader and want to upgrade, and someone
                    # else also wants to upgrade, there is no way we can do
                    # this except if one of us releases all his read locks.
                    # Signal this to user.
                    raise ValueError(
                        "Inevitable dead lock, denying write lock"
                    )
                upgradewriter = True
                self.__upgradewritercount = self.__readers.pop(me)
            else:
                # We aren't a reader, so add us to the pending writers queue
                # for synchronization with the readers.
                self.__pendingwriters.append(me)
            while True:
                if not self.__readers and self.__writer is None:
                    # Only test anything if there are no readers and writers.
                    if self.__upgradewritercount:
                        if upgradewriter:
                            # There is a writer to upgrade, and it's us. Take
                            # the write lock.
                            self.__writer = me
                            self.__writercount = self.__upgradewritercount + 1
                            self.__upgradewritercount = 0
                            return
                        # There is a writer to upgrade, but it's not us.
                        # Always leave the upgrade writer the advance slot,
                        # because he presumes he'll get a write lock directly
                        # from a previously held read lock.
                    elif self.__pendingwriters[0] is me:
                        # If there are no readers and writers, it's always
                        # fine for us to take the writer slot, removing us
                        # from the pending writers queue.
                        # This might mean starvation for readers, though.
                        self.__writer = me
                        self.__writercount = 1
                        self.__pendingwriters = self.__pendingwriters[1:]
                        return
                if timeout is not None:
                    remaining = endtime - time()
                    if remaining <= 0:
                        # Timeout has expired, signal caller of this.
                        if upgradewriter:
                            # Put us back on the reader queue. No need to
                            # signal anyone of this change, because no other
                            # writer could've taken our spot before we got
                            # here (because of remaining readers), as the test
                            # for proper conditions is at the start of the
                            # loop, not at the end.
                            self.__readers[me] = self.__upgradewritercount
                            self.__upgradewritercount = 0
                        else:
                            # We were a simple pending writer, just remove us
                            # from the FIFO list.
                            self.__pendingwriters.remove(me)
                        raise RuntimeError("Acquiring write lock timed out")
                    self.__condition.wait(remaining)
                else:
                    self.__condition.wait()
        finally:
            self.__condition.release()

    def release(self):
        """Release the currently held lock.

        In case the current thread holds no lock, a ValueError is thrown."""

        me = currentThread()
        self.__condition.acquire()
        try:
            if self.__writer is me:
                # We are the writer, take one nesting depth away.
                self.__writercount -= 1
                if not self.__writercount:
                    # No more write locks; take our writer position away and
                    # notify waiters of the new circumstances.
                    self.__writer = None
                    self.__condition.notifyAll()
            elif me in self.__readers:
                # We are a reader currently, take one nesting depth away.
                self.__readers[me] -= 1
                if not self.__readers[me]:
                    # No more read locks, take our reader position away.
                    del self.__readers[me]
                    if not self.__readers:
                        # No more readers, notify waiters of the new
                        # circumstances.
                        self.__condition.notifyAll()
            else:
                raise ValueError("Trying to release unheld lock")
        finally:
            self.__condition.release()
    release_read = release
    release_write = release


##########################################################################
# name-based read/write item
##########################################################################

import thread


class ReadWriteLockItem:
    """ an item for name-based r/w lock hash """

    def __init__(self):
        self.readers = 0
        self.writers = 0
        self.lock = ReadWriteLock()

    def users(self):
        return self.readers + self.writers

    def acquire_read(self, timeout=None):
        self.lock.acquire_read(timeout=timeout)

    def release_read(self):
        self.lock.release_read()

    def acquire_write(self, timeout=None):
        self.lock.acquire_write(timeout=timeout)

    def release_write(self):
        self.lock.release_write()

##########################################################################
# name-based read/write lock
##########################################################################


class HashedReadWriteLock:
    """ A name-based lock object that allows many simultaneous "read locks", but
    only one "write lock." """

    def __init__(self):
        self._names = {}
        self._hash_lock = thread.allocate_lock()

    def acquire_read(self, name, timeout=None):
        """ Acquire a read lock. Blocks only if a thread has
        acquired the write lock. """
        self._hash_lock.acquire()
        if name not in self._names:
            self._names[name] = ReadWriteLockItem()
        self._names[name].readers += 1
        self._hash_lock.release()
        self._names[name].acquire_read(timeout=timeout)

    def release_read(self, name):
        """ Release a read lock. """
        self._hash_lock.acquire()
        if name in self._names:
            self._names[name].release_read()
            self._names[name].readers -= 1
            if self._names[name].users() == 0:
                del self._names[name]
        self._hash_lock.release()

    def acquire_write(self, name, timeout=None):
        """ Acquire a write lock. Blocks until there are no
        acquired read or write locks. """
        self._hash_lock.acquire()
        if name not in self._names:
            self._names[name] = ReadWriteLockItem()
        self._names[name].writers += 1
        self._hash_lock.release()
        self._names[name].acquire_write(timeout=timeout)

    def release_write(self, name):
        """ Release a write lock. """
        self._hash_lock.acquire()
        if name in self._names:
            self._names[name].release_write()
            self._names[name].writers -= 1
            if self._names[name].users() == 0:
                del self._names[name]
        self._hash_lock.release()
