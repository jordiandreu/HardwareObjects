"""
[Name] Marvin

[Description]
Hardware object for Marvin sample changer

[Channels]

[Commands]

[Emited signals]

[Included Hardware Objects]
-----------------------------------------------------------------------
| name            | signals          | functions
-----------------------------------------------------------------------
-----------------------------------------------------------------------
"""

import logging
import time
import datetime
from sample_changer.GenericSampleChanger import *


class Marvin(SampleChanger):
    """
    """    
    __TYPE__ = "Marvin"    

    def __init__(self, *args, **kwargs):
        super(Marvin, self).__init__(self.__TYPE__,False, *args, **kwargs)
        self._selected_sample = None
        self._selected_basket = None
        self._scIsCharging = None

        self._num_baskets = None
        self._status_string = None
        self._state_string = None
        self._puck_switches = None
        self._mounted_puck = None
        self._mounted_sample = None
        self._action_started = None
        self._progress = None
        self._veto = None
        self._sample_detected = None

        self.chan_status = None
        self.chan_sample_is_loaded = None
        self.chan_puck_switched = None
        self.chan_mounted_sample_puck = None

        self.cmd_mount_sample = None
        self.cmd_unmount_sample = None
        self.cmd_dry_gripper = None

        self.detector_distance_hwobj = None 

            
    def init(self):      
        self._puck_switches = 0
        self._num_basket = self.getProperty("numBaskets")
        if not self._num_basket:
            self._num_basket = 16

        for i in range(self._num_basket):
            basket = Basket(self, i + 1)
            self._addComponent(basket)

        self.chan_puck_switches = self.getChannelObject("chanPuckSwitches")
        if self.chan_puck_switches is not None:
            self.chan_puck_switches.connectSignal("update", self.puck_switches_changed)

        self.chan_status = self.getChannelObject("chanStatus")
        if self.chan_status is not None:
            self.chan_status.connectSignal("update", self.status_string_changed)

        self.chan_sample_is_loaded = self.getChannelObject("chanSampleIsLoaded")
        if self.chan_sample_is_loaded is not None:
            self.chan_sample_is_loaded.connectSignal("update", self.sample_is_loaded_changed)

        self.chan_mounted_sample_puck = self.getChannelObject("chanMountedSamplePuck")
        if self.chan_mounted_sample_puck is not None:
            self.chan_mounted_sample_puck.connectSignal("update", self.mounted_sample_puck_changed)

        self.chan_veto = self.getChannelObject("chanVeto")
        if self.chan_veto is not None:
            self.chan_veto.connectSignal("update", self.veto_changed)

        self.cmd_mount_sample = self.getCommandObject("cmdMountSample")
        self.cmd_unmount_sample = self.getCommandObject("cmdUnmountSample")

        self.detector_distance_hwobj = self.getObjectByRole('detector_distance')

        self._initSCContents()
        self._updateState()
        self._updateSCContents()
        self._updateLoadedSample()
        SampleChanger.init(self)

    def run_test(self):
        """
        Test method mounts/dismounts samples
        """
        samples_mounted = 0
        for cycle in range(5):
            for sample_index in range(1, 11):
                logging.getLogger("user_level_log").info("Mounting sample 1:%d" % sample_index)
                self.load("1:%02d" % sample_index, wait=True)
                logging.getLogger("user_level_log").info("Total mounts done: %d" % (samples_mounted + 1))
                samples_mounted += 1
                gevent.sleep(1)                           

    def puck_switches_changed(self, puck_switches):
        """
        Updates puck switches
        """
        self._puck_switches = int(puck_switches)
        self._updateSCContents()
 
    def sample_is_loaded_changed(self, sample_detected):
        if self._sample_detected != sample_detected:
            self._sample_detected = sample_detected
            self._updateLoadedSample()
            self.updateInfo()

    def mounted_sample_puck_changed(self, mounted_sample_puck):
        """
        Updates mounted puck index
        """
        mounted_sample = mounted_sample_puck[0] - 1
        self._mounted_puck = mounted_sample_puck[1] - 1
        if mounted_sample != self._mounted_sample:
            self._mounted_sample = mounted_sample
            self._updateLoadedSample()

    def veto_changed(self, status):
        """
        Veto changed callback. Used to wait for ready
        """
        self._veto = status

    def getSampleProperties(self):
        """
        Gets sample properties
        """
        return (Pin.__HOLDER_LENGTH_PROPERTY__,)
        
    def _doUpdateInfo(self):       
        """
        Updates the sample changers status: mounted pucks, state, 
        currently loaded sample
        """
        pass
        #self._updateState()               
        #self._updateSCContents()
        #call this method if status string changed
        #self._updateLoadedSample()
                    
    def _directlyUpdateSelectedComponent(self, basket_no, sample_no):    
        """
        Directly updates necessary sample
        """
        basket = None
        sample = None
        if basket_no is not None and basket_no>0 and \
           basket_no <=self._num_basket:
            basket = self.getComponentByAddress(Basket.getBasketAddress(basket_no))
            if sample_no is not None and sample_no>0 and \
               sample_no <= len(basket.getSampleList()):
                sample = self.getComponentByAddress(Pin.getSampleAddress(basket_no, sample_no))            
        self._setSelectedComponent(basket)
        self._setSelectedSample(sample)

    def _doSelect(self,component):
        """
        Selects a new component (basket or sample).
        Uses method >_directlyUpdateSelectedComponent< to actually 
        search and select the corrected positions.
        """
        if type(component) in (Pin, Sample):
            selected_basket_no = component.getBasketNo()
            selected_sample_no = component.getIndex()+1
        elif isinstance(component, Container) and ( component.getType() == Basket.__TYPE__):
            selected_basket_no = component.getIndex()+1
            selected_sample_no = None

        self._directlyUpdateSelectedComponent(selected_basket_no, selected_sample_no)
            
    def _doScan(self,component,recursive):
        """
        Scans the barcode of a single sample, puck or recursively even the 
        complete sample changer.
        Not implemented
        """
        print "_doScan TODO"
    
    def _doLoad(self,sample=None):
        """
        Loads a sample on the diffractometer. Performs a simple put operation
        if the diffractometer is empty, and a sample exchange (unmount of 
        old + mount of  new sample) if a sample is already mounted on 
        the diffractometer.
        """
        log = logging.getLogger("user_level_log")
        selected = self.getSelectedSample()

        if sample is not None:
            if sample != selected:
                self._doSelect(sample)
                selected=self.getSelectedSample()
        else:
            if selected is not None:
                 sample = selected
            else:
               raise Exception("No sample selected")

        basket = selected.getBasketNo()
        sample = selected.getVialNo()

        if self.hasLoadedSample():
            if selected==self.getLoadedSample():
                msq = "The sample " + \
                      str(self.getLoadedSample().getAddress()) + \
                      " is already loaded"
                raise Exception(msg)
            else:
                msg = "Sample changer: Unloading sample %d:%d" %(\
                    self._mounted_puck, self._mounted_sample)
                self.emit("progressInit", (msg, 100))

                if self.detector_distance_hwobj.getPosition() < 499.0:
                    log.info("Moving detector to save position")
                    self.detector_distance_hwobj.move(500, wait=True)

                logging.getLogger("user_level_log").debug(msg + ". Please wait...")
                self._executeServerTask(self.cmd_unmount_sample,
                                        self._mounted_sample,
                                        self._mounted_puck)
                log.debug("Sample changer: Sample unloading done")

                msg = "Sample changer: Loading sample %d:%d" %(\
                    int(basket), int(sample))
                log.debug(msg + ". Please wait...")
                self.emit("progressInit", (msg, 100))
                self._executeServerTask(self.cmd_mount_sample,
                                        int(sample),
                                        int(basket))
                log.debug("Sample changer: Sample loading done")
        else:
            msg = "Sample changer: Loading sample %d:%d" %(\
                    int(basket), int(sample))
            self.emit("progressInit", (msg, 100))

            if self.detector_distance_hwobj.getPosition() < 499.0:
                log.info("Moving detector to save position")
                self.detector_distance_hwobj.move(500, wait=True)

            logging.getLogger("user_level_log").info(msg + " Please wait...")
            self._executeServerTask(self.cmd_mount_sample,
                                    int(sample),
                                    int(basket))
            log.info("Sample changer: Sample loading done")

    def _doUnload(self, sample_slot = None):
        """
        Unloads a sample from the diffractometer.
        """
        msg = "Sample changer: Unloading sample %d:%d" %(\
                    self._mounted_puck, self._mounted_sample)
        self.emit("progressInit", (msg, 100))

        if self.detector_distance_hwobj.getPosition() < 499.0:
            logging.getLogger("user_level_log").info("Moving detector to save position")
            self.detector_distance_hwobj.move(500, wait=True)

        logging.getLogger("user_level_log").info(msg + ". Please wait...")
        self._executeServerTask(self.cmd_unmount_sample,
                                int(self._mounted_sample),
                                int(self._mounted_puck))
        logging.getLogger("user_level_log").info("Sample changer: Sample unloading done") 

    def clearBasketInfo(self, basket):
        """
        Clears information about basket
        """
        #TODO
        return

    def _doChangeMode(self, mode):
        """
        Changes the mode of sample changer
        """
        return

    def _doAbort(self):
        """
        Aborts the sample changer.
        """
        return

    def _doReset(self):
        """
        Clean all sample info, move sample to his position and move puck 
        from center to base
        """
        self._initSCContents() 

    def _updateOperationMode(self, value):
        """
        Updates sample operation mode
        """
        self._scIsCharging = not value

    def _executeServerTask(self, method, *args):
        """
        Executes called cmd, waits until sample changer is ready and updates
        loaded sample info
        """
        self._action_started = True
        self._state_string = "Bsy"
        arg_arr = []
        for arg in args:
            arg_arr.append(arg)
        task_id = method(arg_arr)
        gevent.sleep(1)
        self.waitReady(120.0)
        gevent.sleep(1)
        self._updateLoadedSample()
        self._action_started = False

    def _updateState(self):
        """
        Updates state
        """
        state = self._readState()
        if (state == SampleChangerState.Moving and 
            self._isDeviceBusy(self.getState())):
            return
        self._setState(state)
       
    def _readState(self):
        """
        Converts state string to defined state
        """
        state_converter = { "ALARM": SampleChangerState.Alarm,
                            "Idl": SampleChangerState.Ready,
                            "Bsy": SampleChangerState.Moving }
        return state_converter.get(self._state_string, SampleChangerState.Unknown)
                        
    def _isDeviceBusy(self, state=None):
        """
        Checks whether Sample changer is busy.
        """
        if state is None:
            state = self._readState()
        if self._progress >= 100 and state in (SampleChangerState.Ready, 
                                               SampleChangerState.Loaded,
                                               SampleChangerState.Alarm, 
                                               SampleChangerState.Disabled, 
                                               SampleChangerState.Fault, 
                                               SampleChangerState.StandBy):
            return False
        else:
            return True

    def _isDeviceReady(self):
        """
        Checks whether Sample changer is ready.
        """
        state = self._readState()
        return state in (SampleChangerState.Ready, SampleChangerState.Charging)              

    def waitReady(self, timeout=None):
        """
        Waits until the samle changer is ready.
        """
        with gevent.Timeout(timeout, Exception("Timeout waiting for device ready")):
            while not self._isDeviceReady():
                gevent.sleep(0.1)
        self.waitVeto(60)
        gevent.sleep(2)

    def waitVeto(self, timeout=None):
        """
        Waits until the sample changer veto flag is ready
        """
        #with gevent.Timeout(timeout)):
        #    while self._veto == 1:
        #        gevent.sleep(0.1)
        for i in range(timeout * 10):
            if self._veto == 0:
                return
            else: 
                gevent.sleep(0.1)
            
    def _updateSelection(self):    
        """
        Updates selected basked and sample 
        """
        basket = None
        sample = None
        try:
          basket_no = self._selected_basket
          if basket_no is not None and basket_no>0 and \
             basket_no <= self._num_basket:
              basket = self.getComponentByAddress(\
                 Basket.getBasketAddress(basket_no))
              sample_no = self._selected_sample
              if sample_no is not None and sample_no>0 and \
                 sample_no <= Basket.NO_OF_SAMPLES_PER_PUCK:
                  sample = self.getComponentByAddress(\
                      Pin.getSampleAddress(basket_no, sample_no))            
        except:
          pass
        self._setSelectedComponent(basket)
        self._setSelectedSample(sample)

    def _updateLoadedSample(self):
        """
        Updates loaded sample
        """
        if self._sample_detected and \
           self._mounted_sample > -1 and self._mounted_puck > -1:
            new_sample = self.getComponentByAddress(\
                  Pin.getSampleAddress(self._mounted_puck, 
                                       self._mounted_sample))
        else:
            new_sample = None

        if self.getLoadedSample() != new_sample:
            old_sample = self.getLoadedSample()
            if old_sample is not None:
                # there was a sample on the gonio
                loaded = False
                has_been_loaded = True
                old_sample._setLoaded(loaded, has_been_loaded)
            if new_sample is not None:
                self._updateSampleBarcode(new_sample)
                loaded = True
                has_been_loaded = True
                new_sample._setLoaded(loaded, has_been_loaded)

    def _updateSampleBarcode(self, sample):
        """
        Updates the barcode of >sample< in the local database 
        after scanning with the barcode reader.
        """
        datamatrix = "NotAvailable"
        scanned = (len(datamatrix) != 0)
        if not scanned:    
            datamatrix = '----------'   
        sample._setInfo(sample.isPresent(), datamatrix, scanned)

    def _initSCContents(self):
        """
        Initializes the sample changer content with default values.
        """
        basket_list= [('', 4)] * self._num_basket
        for basket_index in range(self._num_basket):            
            basket=self.getComponents()[basket_index]
            datamatrix = None
            present = scanned = False
            basket._setInfo(present, datamatrix, scanned)

        # create temporary list with default sample information and indices
        sample_list=[]
        for basket_index in range(self._num_basket):            
            for sample_index in range(10):
                sample_list.append(("", basket_index + 1, sample_index + 1,
                                    1, Pin.STD_HOLDERLENGTH)) 
        # write the default sample information into permanent Pin objects 
        for spl in sample_list:
            sample = self.getComponentByAddress(\
                Pin.getSampleAddress(spl[1], spl[2]))
            datamatrix = None
            present = scanned = loaded = has_been_loaded = False
            sample._setInfo(present, datamatrix, scanned)
            sample._setLoaded(loaded, has_been_loaded)
            sample._setHolderLength(spl[4])    

    def _updateSCContents(self):
        """
        Updates sample changer content
        """
        for basket_index in range(self._num_basket):            
            basket=self.getComponents()[basket_index]

            if (int(self._puck_switches) & pow(2, basket_index) > 0) or \
               (self._mounted_puck == basket_index + 1):
            #f puck_switches & (1 << basket_index):
                # basket was mounted
                present = True
                scanned = False
                datamatrix = None
            else:
                # basket was removed
                present = False
                scanned = False
                datamatrix = None
            basket._setInfo(present, datamatrix, scanned)
            # set the information for all dependent samples
            for sample_index in range(10):
                sample = self.getComponentByAddress(Pin.getSampleAddress(\
                    (basket_index + 1), (sample_index + 1)))
                present = sample.getContainer().isPresent()
                if present:
                    datamatrix = '%d:%d - Not defined' % \
                       (basket_index, sample_index)
                else:
                    datamatrix = None
                datamatrix = None
                scanned = False
                sample._setInfo(present, datamatrix, scanned)
                # forget about any loaded state in newly mounted or removed basket)
                loaded = has_been_loaded = False
                sample._setLoaded(loaded, has_been_loaded)

    def status_string_changed(self, status_string):
        """
        Status string change event. Converts status string to parameters.
        - Rob: robot status
        - Mag: magnet off or on
        - SDet: sample detected or not detected
        - CDor: cage door opened or closed
        - CPuck: center puck index
        - Prgs: progress 0 - 100
        """
        self._status_string = status_string[:180].replace(" ", "")
        status_list = self._status_string.split(';')

        for status in status_list:
            property_status_list = status.split(':')
            if len(property_status_list) < 2:
                continue
            prop_name = property_status_list[0]
            prop_value = property_status_list[1]
            if prop_name == "Rob":
                if self._state_string != prop_value:
                    self._state_string = prop_value
                    self._updateState()
            elif prop_name == "Prgs":
                try:
                   if int(prop_value) != self._progress and self._action_started:
                       self._progress = int(prop_value)
                       self.emit("progressStep", self._progress)
                except:
                   pass
