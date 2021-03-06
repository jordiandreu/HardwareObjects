#
#  Project: MXCuBE
#  https://github.com/mxcube.
#
#  This file is part of MXCuBE software.
#
#  MXCuBE is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  MXCuBE is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with MXCuBE.  If not, see <http://www.gnu.org/licenses/>.

"""
AbstractMulticollect
Defines a sequence how data collection is executed.
"""

import os
import sys
import logging
import time
import errno
import abc
import collections
import gevent
import queue_model_objects_v1 as queue_model_objects
from HardwareRepository.TaskUtils import *

__credits__ = ["MXCuBE colaboration"]
__version__ = "2.2."
__status__ = "Draft"

BeamlineConfig = collections.namedtuple('BeamlineConfig',
                                        ['synchrotron_name',
                                         'directory_prefix',
                                         'default_exposure_time',
                                         'minimum_exposure_time',
                                         'detector_fileext',
                                         'detector_type',
                                         'detector_manufacturer',
                                         'detector_model',
                                         'detector_px',
                                         'detector_py',
                                         'undulators',
                                         'focusing_optic', 
                                         'monochromator_type', 
                                         'beam_divergence_vertical',
                                         'beam_divergence_horizontal',
                                         'polarisation',
                                         'input_files_server'])


class AbstractCollect(object):
    __metaclass__ = abc.ABCMeta

    def __init__(self):
        self.bl_config = BeamlineConfig(*[None]*17)
        
        self.data_collect_task = None
        self.current_dc_parameters = None
        self.current_lims_sample = {}
        self.run_processing_after = None
        self.run_processing_parallel = None

        self.autoprocessing_hwobj = None
        self.beam_info_hwobj = None
        self.detector_hwobj = None
        self.diffractometer_hwobj = None
        self.energy_hwobj = None
        self.lims_client_hwobj = None
        self.machine_info__hwobj = None
        self.resolution_hwobj = None
        self.sample_changer_hwobj = None
        self.transmission_hwobj = None

        self.ready_event = gevent.event.Event()

    def set_beamline_configuration(self, **configuration_parameters):
        self.bl_config = BeamlineConfig(**configuration_parameters)

    def collect(self, owner, dc_parameters_list):
        """
        Main collect method.   
        """
        self.ready_event.clear()
        self.current_dc_parameters = dc_parameters_list[0]
        self.data_collect_task = gevent.spawn(self.do_collect, owner)
        self.ready_event.wait()
        self.ready_event.clear()
        return self.data_collect_task

    def do_collect(self, owner):
        """
        Actual collect sequence
        """
        log = logging.getLogger("user_level_log")
        log.info("Collection: Preparing to collect")
        self.emit("collectReady", (False, ))
        self.emit("collectOscillationStarted", (owner, None, \
                  None, None, self.current_dc_parameters, None))

        # ----------------------------------------------------------------
        self.open_detector_cover()
        self.open_safety_shutter()
        self.open_fast_shutter()

        # ----------------------------------------------------------------
        self.current_dc_parameters["status"] = "Running"
        self.current_dc_parameters["collection_start_time"] = \
             time.strftime("%Y-%m-%d %H:%M:%S")
     
        log.info("Collection: Storing data collection in LIMS") 
        self.store_data_collection_in_lims()
       
        log.info("Collection: Creating directories for raw images and processing files") 
        self.create_file_directories()

        log.info("Collection: Getting sample info from parameters") 
        self.get_sample_info()
        
        #log.info("Collect: Storing sample info in LIMS")        
        #self.store_sample_info_in_lims()

        if all(item == None for item in self.current_dc_parameters['motors'].values()):
            # No centring point defined
            # create point based on the current position
            current_diffractometer_position = self.diffractometer_hwobj.getPositions()
            for motor in self.current_dc_parameters['motors'].keys():
                self.current_dc_parameters['motors'][motor] = \
                     current_diffractometer_position.get(motor) 

        log.info("Collection: Moving to centred position") 
        self.move_to_centered_position()
        self.take_crystal_snapshots()
        self.move_to_centered_position()

        if "transmission" in self.current_dc_parameters:
            log.info("Collection: Setting transmission to %.3f", 
                     self.current_dc_parameters["transmission"])
            self.set_transmission(self.current_dc_parameters["transmission"])

        if "wavelength" in self.current_dc_parameters:
            log.info("Collection: Setting wavelength to %.3f", \
                     self.current_dc_parameters["wavelength"])
            self.set_wavelength(self.current_dc_parameters["wavelength"])

        elif "energy" in self.current_dc_parameters:
            log.info("Collection: Setting energy to %.3f",  
                     self.current_dc_parameters["energy"])
            self.set_energy(self.current_dc_parameters["energy"])

        if "resolution" in self.current_dc_parameters:
            resolution = self.current_dc_parameters["resolution"]["upper"]
            log.info("Collection: Setting resolution to %.3f", resolution)
            self.set_resolution(resolution)

        elif 'detdistance' in self.current_dc_parameters:
            log.info("Collection: Moving detector to %f", 
                     self.current_dc_parameters["detdistance"])
            self.move_detector(self.current_dc_parameters["detdistance"])

        log.info("Collection: Updating data collection in LIMS")
        self.update_data_collection_in_lims()
        self.data_collection_hook()
        # ----------------------------------------------------------------

        self.close_fast_shutter()
        self.close_safety_shutter()
        self.close_detector_cover()

    def data_collection_cleanup(self, owner="MXCuBE"):
        """
        Method called when an error is raised during the collectin.        
        """

        logging.exception("Data collection failed")
        self.current_dc_parameters["status"] = 'failed'
        exc_type, exc_value, exc_tb = sys.exc_info()
        failed_msg = 'Data collection failed!\n%s' % exc_value
        self.emit("collectOscillationFailed", (owner, False, failed_msg, 
           self.current_dc_parameters.get('collection_id'), 1))

    def stop_collect(self, owner="MXCuBE"):
        """
        Stops data collection
        """
        if self.data_collect_task is not None:
            self.data_collect_task.kill(block = False)

    def open_detector_cover(self):
        """
        Descript. : 
        """
        pass

    def open_safety_shutter(self):
        """
        Descript. : 
        """
        pass

    def open_fast_shutter(self):
        """
        Descript. :
        """
        pass

    def close_fast_shutter(self):
        """
        Descript. :
        """
        pass

    def close_safety_shutter(self):
        """
        Descript. :
        """
        pass

    def close_detector_cover(self):
        """
        Descript. :
        """
        pass

    def set_transmission(self, value):
        """
        Descript. :
        """
        pass

    def set_wavelength(self, value):
        """
        Descript. :
        """
        pass

    def set_energy(self, value):
        """
        Descript. :
        """
        pass
    
    def set_resolution(self, value):
        """
        Descript. :
        """
        pass

    def move_detector(self, value):
        """
        Descript. :
        """
        pass

    def get_flux(self):
        """
        Descript. :
        """
        return

    def get_wavelength(self):
        """
        Descript. :
        """
        if self.energy_hwobj is not None:
            return self.energy_hwobj.getCurrentWavelength()

    def get_detector_distance(self):
        """
        Descript. : 
        """
        if self.detector_hwobj is not None:
            return self.detector_hwobj.get_distance()

    def get_resolution(self):
        """
        Descript. : 
        """
        if self.resolution_hwobj is not None:
            return self.resolution_hwobj.getPosition()

    def get_transmission(self):
        """
        Descript. : 
        """
        if self.transmission_hwobj is not None:
            return self.transmission_hwobj.getAttFactor()  

    def get_beam_centre(self):
        """
        Descript. : 
        """
        if self.detector_hwobj is not None:
            return self.detector_hwobj.get_beam_centre()
        else:
            return None, None 

    def get_resolution_at_corner(self):
        """
        Descript. : 
        """
        return

    def get_beam_size(self):
        """
        Descript. : 
        """
        if self.beam_info_hwobj is not None:
            return self.beam_info_hwobj.get_beam_size()
        else:
            return None, None

    def get_slit_gaps(self):
        """
        Descript. : 
        """
        if self.beam_info_hwobj is not None:
            return self.beam_info_hwobj.get_slits_gap()
        return None, None

    def get_undulators_gaps(self):
        """
        Descript. : 
        """
        return {}

    def get_beam_shape(self):
        """
        Descript. : 
        """
        if self.beam_info_hwobj is not None:
            return self.beam_info_hwobj.get_shape()

    def get_machine_current(self):
        """
        Descript. : 
        """
        if self.machine_info_hwobj:
            return self.machine_info_hwobj.get_current()
        else:
            return 0

    def get_machine_message(self):
        """
        Descript. : 
        """
        if self.machine_info_hwobj:
            return self.machine_info_hwobj.get_message()
        else:
            return ''

    def get_machine_fill_mode(self):
        """
        Descript. : 
        """
        if self.machine_info_hwobj:
            fill_mode = str(self.machine_info_hwobj.get_message())
            return fill_mode[:20]
        else:
            return ''

    def get_measured_intensity(self):
        """
        Descript. : 
        """
        return

    def get_cryo_temperature(self):
        """
        Descript. : 
        """
        return

    def create_file_directories(self):
        """
        Method create directories for raw files and processing files.
        Directorie names for xds, mosflm and hkl are created
        """
        self.create_directories(\
            self.current_dc_parameters['fileinfo']['directory'],  
            self.current_dc_parameters['fileinfo']['process_directory'])
        xds_directory, mosflm_directory, hkl2000_directory = \
            self.prepare_input_files()
        if xds_directory:
            self.current_dc_parameters['xds_dir'] = xds_directory

    def create_directories(self, *args):
        """
        Descript. :
        """
        for directory in args:
            try:
                os.makedirs(directory)
            except os.error, e:
                if e.errno != errno.EEXIST:
                    raise

    def prepare_input_files(self):
        """
        Prepares input files for xds, mosflm and hkl2000
        returns: 3 strings
        """

        return None, None, None

    def store_data_collection_in_lims(self):
        """
        Descript. : 
        """
        if self.lims_client_hwobj and not self.current_dc_parameters['in_interleave']:
            try:
                self.current_dc_parameters["synchrotronMode"] = \
                     self.get_machine_fill_mode()
                (collection_id, detector_id) = self.lims_client_hwobj.\
                  store_data_collection(self.current_dc_parameters, 
                                        self.bl_config)
                self.current_dc_parameters['collection_id'] = collection_id  
                if detector_id:
                    self.current_dc_parameters['detector_id'] = detector_id 
            except:
                logging.getLogger("HWR").exception("Could not store data collection in LIMS")

    def update_data_collection_in_lims(self):
        """
        Descript. : 
        """
        if self.lims_client_hwobj and not self.current_dc_parameters['in_interleave']:
            self.current_dc_parameters["flux"] = self.get_flux()
            self.current_dc_parameters["wavelength"] = self.get_wavelength()
            self.current_dc_parameters["detectorDistance"] =  self.get_detector_distance()
            self.current_dc_parameters["resolution"] = self.get_resolution()
            self.current_dc_parameters["transmission"] = self.get_transmission()
            beam_centre_x, beam_centre_y = self.get_beam_centre()
            self.current_dc_parameters["xBeam"] = beam_centre_x
            self.current_dc_parameters["yBeam"] = beam_centre_y
            und = self.get_undulators_gaps()
            i = 1
            for jj in self.bl_config.undulators:
                key = jj.type
                if und.has_key(key):
                    self.current_dc_parameters["undulatorGap%d" % (i)] = und[key]
                    i += 1
            self.current_dc_parameters["resolutionAtCorner"] = self.get_resolution_at_corner()
            beam_size_x, beam_size_y = self.get_beam_size()
            self.current_dc_parameters["beamSizeAtSampleX"] = beam_size_x
            self.current_dc_parameters["beamSizeAtSampleY"] = beam_size_y
            self.current_dc_parameters["beamShape"] = self.get_beam_shape()
            hor_gap, vert_gap = self.get_slit_gaps()
            self.current_dc_parameters["slitGapHorizontal"] = hor_gap
            self.current_dc_parameters["slitGapVertical"] = vert_gap
            try:
               self.lims_client_hwobj.update_data_collection(self.current_dc_parameters)
            except:
               logging.getLogger("HWR").exception("Could not update data collection in LIMS")

    def store_sample_info_in_lims(self):
        """
        Descript. : 
        """
        if self.lims_client_hwobj and not self.current_dc_parameters['in_interleave']:
            self.lims_client_hwobj.update_bl_sample(self.current_lims_sample)

    def store_image_in_lims(self, frame_number, motor_position_id=None):
        """
        Descript. :
        """
        if self.lims_client_hwobj and not self.current_dc_parameters['in_interleave']:
            file_location = self.current_dc_parameters["fileinfo"]["directory"]
            image_file_template = self.current_dc_parameters['fileinfo']['template']
            filename = image_file_template % frame_number
            lims_image = {'dataCollectionId': self.current_dc_parameters["collection_id"],
                          'fileName': filename,
                          'fileLocation': file_location,
                          'imageNumber': frame_number,
                          'measuredIntensity': self.get_measured_intensity(),
                          'synchrotronCurrent': self.get_machine_current(),
                          'machineMessage': self.get_machine_message(),
                          'temperature': self.get_cryo_temperature()}
            archive_directory = self.current_dc_parameters['fileinfo']['archive_directory']
            if archive_directory:
                jpeg_filename = "%s.jpeg" % os.path.splitext(image_file_template)[0]
                thumb_filename = "%s.thumb.jpeg" % os.path.splitext(image_file_template)[0]
                jpeg_file_template = os.path.join(archive_directory, jpeg_filename)
                jpeg_thumbnail_file_template = os.path.join(archive_directory, thumb_filename)
                jpeg_full_path = jpeg_file_template % frame_number
                jpeg_thumbnail_full_path = jpeg_thumbnail_file_template % frame_number
                lims_image['jpegFileFullPath'] = jpeg_full_path
                lims_image['jpegThumbnailFileFullPath'] = jpeg_thumbnail_full_path
            if motor_position_id:
                lims_image['motorPositionId'] = motor_position_id
            image_id = self.lims_client_hwobj.store_image(lims_image) 
            return image_id

    def get_sample_info(self):
        """
        Descript. : 
        """
        sample_info = self.current_dc_parameters.get("sample_reference")
        try:
            sample_id = int(sample_info["blSampleId"])
        except:
            sample_id = None

        try:
            sample_code = sample_info["code"]
        except:
            sample_code = None

        sample_location = None

        try:
            sample_container_number = int(sample_info['container_reference'])
        except:
            pass
        else:
            try:
                vial_number = int(sample_info["sample_location"])
            except:
                pass
            else:
                sample_location = (sample_container_number, vial_number)
 
        self.current_dc_parameters['blSampleId'] = sample_id
        if self.sample_changer_hwobj:
            try:
                self.current_dc_parameters["actualSampleBarcode"] = \
                    self.sample_changer_hwobj.getLoadedSample().getID()
                self.current_dc_parameters["actualContainerBarcode"] = \
                    self.sample_changer_hwobj.getLoadedSample().getContainer().getID()

                logging.getLogger("user_level_log").info("Getting loaded sample coords")
                basket, vial = self.sample_changer_hwobj.getLoadedSample().getCoords()

                self.current_dc_parameters["actualSampleSlotInContainer"] = vial
                self.current_dc_parameters["actualContainerSlotInSC"] = basket
            except:
                self.current_dc_parameters["actualSampleBarcode"] = None
                self.current_dc_parameters["actualContainerBarcode"] = None
        else:
            self.current_dc_parameters["actualSampleBarcode"] = None
            self.current_dc_parameters["actualContainerBarcode"] = None


    def move_to_centered_position(self):
        """
        Descript. : 
        """
        positions_str = ""
        for motor, position in self.current_dc_parameters['motors'].iteritems():
            if position:
                if isinstance(motor, str):
                    positions_str += " %s=%f" % (motor, position)
                else:
                    positions_str += " %s=%f" % (motor.getMotorMnemonic(), position)
        self.current_dc_parameters['actualCenteringPosition'] = positions_str
        self.move_motors(self.current_dc_parameters['motors'])

    @abc.abstractmethod
    @task
    def move_motors(self, motor_position_dict):
        """
        Descript. : 
        """
        return

    def take_crystal_snapshots(self):
        """
        Descript. : 
        """
        number_of_snapshots = self.current_dc_parameters["take_snapshots"]
        if number_of_snapshots > 0 and not self.current_dc_parameters["in_interleave"]:
            snapshot_directory = self.current_dc_parameters["fileinfo"]["archive_directory"]
            if not os.path.exists(snapshot_directory):
                try:
                    self.create_directories(snapshot_directory)
                except:
                    logging.getLogger("HWR").exception("Collection: Error creating snapshot directory")

            logging.getLogger("user_level_log").info(\
                 "Collection: Taking %d sample snapshot(s)" % number_of_snapshots)
            for snapshot_index in range(number_of_snapshots):
                snapshot_filename = os.path.join(\
                       snapshot_directory,
                       "%s_%s_%s.snapshot.jpeg" % (\
                       self.current_dc_parameters["fileinfo"]["prefix"],
                       self.current_dc_parameters["fileinfo"]["run_number"],
                       (snapshot_index + 1)))
                self.current_dc_parameters['xtalSnapshotFullPath%i' % \
                    (snapshot_index + 1)] = snapshot_filename
                self._take_crystal_snapshot(snapshot_filename)
                if number_of_snapshots > 1:
                    self.diffractometer_hwobj.move_omega_relative(90)
        
    @abc.abstractmethod
    @task
    def _take_crystal_snapshot(self, snapshot_filename):
        """
        Depends on gui version how this method is implemented.
        In Qt3 diffractometer has a function,
        In Qt4 graphics_manager is making crystal snapshots
        """
        pass

    @abc.abstractmethod
    def data_collection_hook(self):
        """
        Descript. : 
        """
        pass

    @abc.abstractmethod
    def trigger_auto_processing(self, process_event, frame_number):
        """
        Descript. : 
        """
        pass

    def set_helical(self, arg):
        """
        Descript. : 
        """
        pass

    def set_helical_pos(self, arg):
        """
        Descript. : 
        """
        pass

    def setMeshScanParameters(self, num_lines, num_images_per_line, mesh_range):
        """
        Descript. : 
        """
        pass

    def setCentringStatus(self, status):
        """
        Descript. : 
        """
        pass

    def prepare_interleave(self, data_model, param_list):
        self.current_dc_parameters = param_list[0]
        self.current_dc_parameters["status"] = "Running"
        self.current_dc_parameters["collection_start_time"] = \
             time.strftime("%Y-%m-%d %H:%M:%S")
        self.take_crystal_snapshots()

        self.store_data_collection_in_lims()
        self.current_dc_parameters["status"] = \
             "Data collection successful"
        self.update_data_collection_in_lims()
