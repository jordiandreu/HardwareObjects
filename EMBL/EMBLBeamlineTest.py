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
[Name] EMBLBeamlineTest

[Description]
EMBLBeamlineTest HO uses beamfocusing HO, ppucontrol HO and md HO to perform 
beamline tests. 

[Channels]

[Commands]

[Emited signals]

[Functions]
 
[Included Hardware Objects]
-----------------------------------------------------------------------
| name                 | signals        | functions
-----------------------------------------------------------------------
| beamline_setup_hwobj |                |  
-----------------------------------------------------------------------

Example Hardware Object XML file :
==================================
<procedure class="BeamTestTool">
    <defaultCsvFileName>/home/karpics/beamlinesw/trunk/beamline/p14/app/
             beamline-test-tool/p14devicesList.csv</defaultCsvFileName>
    <focusing>/beamFocusing</focusing>
    <ppu>/PPUControl</ppu>
    <md>/minidiffdummy</md>
</procedure>
"""

import os
import tine
import numpy
import gevent
import logging
import tempfile
from csv import reader
from datetime import datetime
from random import random

from scipy.interpolate import interp1d
from matplotlib.figure import Figure
from matplotlib.backends.backend_agg import FigureCanvasAgg

import SimpleHTML
from HardwareRepository.BaseHardwareObjects import HardwareObject


__author__ = "Ivars Karpics"
__credits__ = ["MXCuBE colaboration"]
__version__ = "2.2."


TEST_DICT = {"summary": "Beamline summary",
             "com": "Communication with beamline devices",
             "ppu": "PPU control",
             "focusing": "Focusing modes",
             "aperture": "Aperture",
             "alignbeam": "Align beam position",
             "attenuators": "Attenuators",
             "autocentring": "Auto centring procedure",
             "measure_intensity": "Intensity measurement",
             "graph": "Graph"}

TEST_COLORS_TABLE = {False : '#FFCCCC', True : '#CCFFCC'}
TEST_COLORS_FONT = {False : '#FE0000', True : '#007800'}

#ENERGY_RESPON = ((4, ),
#                 ())


class EMBLBeamlineTest(HardwareObject):
    """
    Description:
    """

    def __init__(self, name):
        """
        Descrip. :
        """
        HardwareObject.__init__(self, name)

        self.ready_event = None
        self.devices_list = None
        self.csv_file = None
        self.csv_file_name = None
        self.test_queue_dict = None
        self.comm_test = None
        self.current_test_procedure = None
        self.beamline_name = None
        self.test_directory = None
        self.test_source_directory = None
        self.test_filename = None

        self.scale_hor = None
        self.scale_ver = None
        self.scan_status = None

        self.available_tests_dict = {}
        self.startup_test_list = []
        self.results_list = None
        self.results_html_list = None
        self.arhive_results = None
        self.graph_values = [[], []]

        self.chan_pitch_scan_status = None
        self.cmd_start_pitch_scan = None
        self.cmd_set_vmax_pitch = None

        self.bl_hwobj = None
        self.crl_hwobj = None
        self.beam_focusing_hwobj = None
        self.graphics_manager_hwobj = None
        self.horizontal_motor_hwobj = None
        self.vertical_motor_hwobj = None
        self.graphics_manager_hwobj = None

        self.diode_calibration_amp_per_watt = interp1d(\
              [4., 6., 8., 10., 12., 12.5, 15., 16., 20., 30.], 
              [0.2267, 0.2116, 0.1405, 0.086, 0.0484, 0.0469,
               0.0289, 0.0240, 0.01248, 0.00388])

        self.air_absorption_coeff_per_meter = interp1d(\
               [4., 6.6, 9.2, 11.8, 14.4, 17., 19.6, 22.2, 24.8, 27.4, 30],
               [9.19440446, 2.0317802, 0.73628084, 0.34554261,
                0.19176669, 0.12030697, 0.08331135, 0.06203213,
                0.04926173,  0.04114024, 0.0357374 ])
        self.carbon_window_transmission = interp1d(\
               [4., 6.6, 9.2, 11.8, 14.4, 17., 19.6, 22.2, 24.8, 27.4, 30],
               [0.74141, 0.93863, 0.97775, 0.98946, 0.99396,
                0.99599, 0.99701, 0.99759, 0.99793, 0.99815, 0.99828])
        self.dose_rate_per_10to14_ph_per_mmsq = interp1d(\
               [4., 6.6, 9.2, 11.8, 14.4, 17., 19.6, 22.2, 24.8, 27.4, 30.0],
               [459000., 162000., 79000., 45700., 29300., 20200.,
                14600., 11100., 8610., 6870., 5520.])

    def init(self):
        """
        Descrip. :
        """
        self.ready_event = gevent.event.Event()

        self.scale_hor = self.getProperty("scale_hor")
        self.scale_ver = self.getProperty("scale_ver")

        self.chan_pitch_scan_status = self.getChannelObject("chanPitchScanStatus")
        self.connect(self.chan_pitch_scan_status, "update", self.pitch_scan_status_changed)

        self.cmd_start_pitch_scan = self.getCommandObject("cmdStartPitchScan")
        self.cmd_set_vmax_pitch = self.getCommandObject("cmdSetVMaxPitch")

        self.horizontal_motor_hwobj = self.getObjectByRole("horizontal_motor")
        self.vertical_motor_hwobj = self.getObjectByRole("vertical_motor")

        self.bl_hwobj = self.getObjectByRole("beamline_setup")
        self.crl_hwobj = self.getObjectByRole("crl")
        self.graphics_manager_hwobj = self.bl_hwobj.shape_history_hwobj
        self.beam_align_hwobj = self.getObjectByRole("beam_align")

        try:
           self.beam_focusing_hwobj = self.bl_hwobj.beam_info_hwobj.beam_focusing_hwobj
           self.connect(self.beam_focusing_hwobj,
                        "focusingModeChanged",
                        self.focusing_mode_changed)
        except:
           logging.getLogger("HWR").warning("BeamlineTest: Beam focusing hwobj is not defined")

        if hasattr(self.bl_hwobj, "ppu_control_hwobj"):
            self.connect(self.bl_hwobj.ppu_control_hwobj,
                         "ppuStatusChanged",
                          self.ppu_status_changed)
        else:
            logging.getLogger("HWR").warning("BeamlineTest: PPU control hwobj is not defined")

        self.beamline_name = self.bl_hwobj.session_hwobj.beamline_name 
        self.csv_file_name = self.getProperty("device_list")
        self.init_device_list()  

        self.test_directory = self.getProperty("results_directory")
        if self.test_directory is None:
            self.test_directory = os.path.join(\
                tempfile.gettempdir(), "mxcube", "beamline_test")
            logging.getLogger("HWR").debug("BeamlineTest: directory for test " \
                "reports not defined. Set to: %s" % self.test_directory)
        self.test_source_directory = os.path.join(\
             self.test_directory,
             datetime.now().strftime("%Y_%m_%d_%H") + "_source")

        self.test_filename = "mxcube_test_report.html"

        try:
            for test in eval(self.getProperty("available_tests")):
                self.available_tests_dict[test] = TEST_DICT[test]
        except:
            logging.getLogger("HWR").debug("BeamlineTest: Available tests are " +\
                "not defined in xml. Setting all tests as available.")
        if self.available_tests_dict is None:
            self.available_tests_dict = TEST_DICT

        try:
            self.startup_test_list = eval(self.getProperty("startup_tests"))
        except:
            logging.getLogger("HWR").debug('BeamlineTest: Test list not defined.')

        if self.getProperty("run_tests_at_startup") == True:
            self.start_test_queue(self.startup_test_list)

        self.arhive_results = self.getProperty("arhive_results")

        self.intensity_ranges = []
        self.intensity_measurements = []
        try:
           for intens_range in self['intensity']['ranges']:
               temp_intens_range = {}
               temp_intens_range['max'] = intens_range.CurMax
               temp_intens_range['index'] = intens_range.CurIndex
               temp_intens_range['offset'] = intens_range.CurOffset
               self.intensity_ranges.append(temp_intens_range)
           self.intensity_ranges = sorted(self.intensity_ranges, key=lambda item: item['max'])
        except:
           logging.getLogger("HWR").error("BeamlineTest: no intensity ranges defined")

        self.chan_intens_mean = self.getChannelObject('intensMean')
        self.chan_intens_range = self.getChannelObject('intensRange')

        self.cmd_set_intens_resolution = self.getCommandObject('setIntensResolution')
        self.cmd_set_intens_acq_time = self.getCommandObject('setIntensAcqTime')
        self.cmd_set_intens_range = self.getCommandObject('setIntensRange')

    def start_test_queue(self, test_list, create_report=True):
        """
        Descrip. :
        """
        if create_report:
            try:
                logging.getLogger("HWR").debug(\
                    "BeamlineTest: Creating directory %s" % \
                    self.test_directory)
                if not os.path.exists(self.test_directory):
                    os.makedirs(self.test_directory)
                
                logging.getLogger("HWR").debug(\
                    "BeamlineTest: Creating source directory %s" % \
                    self.test_source_directory)
                if not os.path.exists(self.test_source_directory):
                    os.makedirs(self.test_source_directory)
            except:
                logging.getLogger("HWR").warning(\
                   "BeamlineTest: Unable to create test directories")
                return 

        self.results_list = []
        self.results_html_list = []
        for test_index, test_name in enumerate(test_list):
            test_method_name = "test_" + test_name.lower()
            if hasattr(self, test_method_name):
                if TEST_DICT.has_key(test_name):
                    logging.getLogger("HWR").debug(\
                         "BeamlineTest: Executing test %s (%s)" \
                         % (test_name, TEST_DICT[test_name]))

                    progress_info = {"progress_total": len(test_list),
                                     "progress_msg": "executing %s" % TEST_DICT[test_name]}
                    self.emit("testProgress", (test_index, progress_info))

                    start_time =  datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self.current_test_procedure = gevent.spawn(\
                         getattr(self, test_method_name))
                    test_result = self.current_test_procedure.get()

                    #self.ready_event.wait()
                    #self.ready_event.clear()
                    end_time =  datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                    self.results_list.append({"short_name": test_name,
                                              "full_name": TEST_DICT[test_name],
                                              "result_bit": test_result.get("result_bit", False),
                                              "result_short": test_result.get("result_short", ""),
                                              "start_time": start_time,
                                              "end_time": end_time})
                  
                    self.results_html_list.append("<h2 id=%s>%s</h2>" % \
                         (test_name, TEST_DICT[test_name]))
                    self.results_html_list.append("Started: %s<br>" % \
                         start_time)
                    self.results_html_list.append("Ended: %s<br>" % \
                         end_time)
                    if test_result.get("result_short"):
                        self.results_html_list.append(\
                            "<h3><font color=%s>Result : %s</font></h3>" % \
                            (TEST_COLORS_FONT[test_result["result_bit"]],
                            test_result["result_short"]))
                    if len(test_result.get("result_details", [])) > 0:
                        self.results_html_list.append("<h3>Detailed results:</h3>")
                        self.results_html_list.extend(test_result.get("result_details", []))
            else:
                msg = "<h2><font color=%s>Execution method %s " + \
                      "for the test %s does not exist</font></h3>"
                self.results_html_list.append(msg %(TEST_COLORS_FONT[False], 
                     test_method_name, TEST_DICT[test_name]))
                logging.getLogger("HWR").error("BeamlineTest: Test method %s not available" % test_method_name)
            self.results_html_list.append("</p>\n<hr>")

        html_filename = None
        if create_report: 
            html_filename = os.path.join(self.test_directory, 
                                         self.test_filename)
            self.generate_html_report()

        self.emit('testFinished', html_filename) 

    def init_device_list(self):
        """
        Descrip. :
        """
        self.devices_list = []
        if os.path.exists(self.csv_file_name): 
            with open(self.csv_file_name, 'rb') as csv_file:
                csv_reader = reader(csv_file, delimiter = ',')
                for row in csv_reader:
                    if self.valid_ip(row[1]):
                        self.devices_list.append(row)
            return self.devices_list
        else:
            logging.getLogger("HWR").error("BeamlineTest: Device file %s not found" %self.csv_file_name)

    def get_device_list(self):
        """
        Descrip. :
        """
        return self.devices_list

    def focusing_mode_changed(self, focusing_mode, beam_size):
        """
        Descrip. :
        """
        self.emit("focusingModeChanged", focusing_mode, beam_size)
    
    def get_focus_mode_names(self):	 
        """
        Descrip. :
        """
        if self.beam_focusing_hwobj:
            return self.beam_focusing_hwobj.get_focus_mode_names()

    def get_focus_motors(self):
        """
        Descript. :
        """
        if self.beam_focusing_hwobj is not None:
            return self.beam_focusing_hwobj.get_focus_motors()

    def get_focus_mode(self):
        """
        Descript. :
        """
        if self.beam_focusing_hwobj is not None:
            return self.beam_focusing_hwobj.get_active_focus_mode()
        else:
            return None, None

    def set_focus_mode(self, mode):
        """
        Descript. :
        """
        if self.beam_focusing_hwobj is not None:
            self.beam_focusing_hwobj.set_focus_mode(mode)

    def set_motor_focus_mode(self, motor, mode):
        """
        Descript. :
        """
        if self.beam_focusing_hwobj is not None:
            self.beam_focusing_hwobj.set_motor_focus_mode(motor, mode)
 
    def valid_ip(self, address):
        """
        Descript. :
        """
        parts = address.split(".")
        if len(parts) != 4:
            return False
        for item in parts:
            try:
                if not 0 <= int(item) <= 255:
                    return False
            except:
                return False
        return True

    def ppu_status_changed(self, is_error, text):
        """
        Descrip. :
        """
        self.emit('ppuStatusChanged', (is_error, text))

    def ppu_restart_all(self):
        """
        Descript. :
        """
        if self.bl_hwobj.ppu_control_hwobj is not None:
            self.bl_hwobj.ppu_control_hwobj.restart_all()

    def test_com(self):
        """
        Descript. :
        """
        result = {} 
        table_header = ["Replied", "DNS name", "IP address", "Location",
                        "MAC address", "Details"] 
        table_cells = []
        failed_count = 0
        for row, device in enumerate(self.devices_list):
            msg = "Pinging %s at %s" % (device[0], device[1])
            logging.getLogger("HWR").debug("BeamlineTest: %s" % msg)
            device_result = ["bgcolor=#FFCCCC" , "False"] + device
            try:
                ping_result = os.system("ping -W 2 -c 2 " + device[1]) == 0
                device_result[0] = "bgcolor=%s" % TEST_COLORS_TABLE[ping_result]
                device_result[1] = str(ping_result)
            except:
                ping_result = False
            table_cells.append(device_result) 

            if not ping_result:
                failed_count += 1
            progress_info = {"progress_total": len(self.devices_list),
                             "progress_msg": msg}
            self.emit("testProgress", (row, progress_info))

        result["result_details"] = SimpleHTML.create_table(table_header, table_cells)

        if failed_count == 0:
            result["result_short"] = "Test passed (got reply from all devices)"
            result["result_bit"] = True
        else:
            result["result_short"] = "Test failed (%d devices from %d did not replied)" % \
                  (failed_count, len(self.devices_list))
            result["result_bit"] = False
        self.ready_event.set()
        return result

    def test_ppu(self):
        """
        Descript. :
        """
        result = {}
        if self.bl_hwobj.ppu_control_hwobj:
            is_error, msg = self.bl_hwobj.ppu_control_hwobj.get_status()
            result["result_bit"] = not is_error
            if result["result_bit"]:
                result["result_short"] = "Test passed"
            else:
                result["result_short"] = "Test failed" 

             
            msg = msg.replace("\n", "\n<br>")
            result["result_details"] = msg.split("\n")
        else:
            result["result_bit"] = False
            result["result_short"]  = "Test failed (ppu hwobj not define)."

        self.ready_event.set()
        return result

    def test_aperture(self):
        """
        Descript. : Test to evaluate beam shape with image processing
                    Depending on the parameters apertures, slits and 
                    focusing modes are tested
        """
        result = {}
        result["result_bit"] = False
        result["result_details"] = [] 

        #got to centring phase

        #check apertures
        table_header = "<table border='1'>\n<tr>" 
        table_values = "<tr>"
        table_result = "<tr>"

        self.bl_hwobj.diffractometer_hwobj.set_phase("BeamLocation", timeout=30)

        aperture_hwobj = self.bl_hwobj.beam_info_hwobj.aperture_hwobj 
        aperture_list = aperture_hwobj.get_aperture_list(as_origin=True)
        current_aperture = aperture_hwobj.get_value() 

        for index, value in enumerate(aperture_list):
            msg = "Selecting aperture %s " % value
            table_header += "<th>%s</th>" % value 
            aperture_hwobj.set_active_position(index)
            gevent.sleep(1)
            beam_image_filename = os.path.join(\
                self.test_source_directory, 
                "aperture_%s.png" % value)
            table_values += "<td><img src=%s style=width:700px;></td>" % beam_image_filename 
            self.graphics_manager_hwobj.save_scene_snapshot(beam_image_filename)
            progress_info = {"progress_total": len(aperture_list),
                             "progress_msg": msg}
            self.emit("testProgress", (index, progress_info))

        self.bl_hwobj.diffractometer_hwobj.set_phase(\
             self.bl_hwobj.diffractometer_hwobj.PHASE_CENTRING, timeout = 30)
        aperture_hwobj.set_active_position(current_aperture)
        table_header += "</tr>"
        table_values += "</tr>"


        result["result_details"].append(table_header)
        result["result_details"].append(table_values)
        result["result_details"].append(table_result)
        result["result_details"].append("</table>")
        result["result_bit"] = True
        self.ready_event.set()
        return result

    def test_graph(self):
        result = {}
        self.graph_values[0].insert(0, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self.graph_values[1].insert(0, random() * 1e12)
        x_arr = range(0, len(self.graph_values[0]))

        result["result_details"] = []
        result["result_details"].append("Intensity graph:")

        fig = Figure(figsize = (15, 11))
        ax = fig.add_subplot(111)
        ax.grid(True)
        ax.plot(x_arr, self.graph_values[1])
        #ax.xticks(x_arr, self.graph_values[0], rotation='vertical')
        ax.xaxis.set_ticks(self.graph_values[0])
        canvas = FigureCanvasAgg(fig)
        graph_path = "/tmp/mxcube/test_graph.png" 
        canvas.print_figure(graph_path) 
        result["result_details"].append("<img src=%s style=width:700px;>" % graph_path)
 
        result["result_short"] = "Done!"
        result["result_bit"] = True
        self.ready_event.set()
        return result
 

    def test_alignbeam(self):
        """
        Descript. :
        """
        result = {}
        result["result_bit"] = False
        result["result_details"] = []
        result["result_short"] = "Test started"

        self.bl_hwobj.diffractometer_hwobj.set_phase(\
             self.bl_hwobj.diffractometer_hwobj.PHASE_BEAM, timeout = 30)

        result["result_details"].append("Beam shape before alignment<br><br>")
        beam_image_filename = os.path.join(self.test_source_directory,
                                           "align_beam_before.png")
        self.graphics_manager_hwobj.save_scene_snapshot(beam_image_filename)
        result["result_details"].append("<img src=%s style=width:300px;><br>" % beam_image_filename)

        self.align_beam()
      
        result["result_details"].append("Beam shape after alignment<br><br>") 
        beam_image_filename = os.path.join(self.test_source_directory,
                                           "align_beam_after.png")
        result["result_details"].append("<img src=%s style=width:300px;><br>" % beam_image_filename)
        self.graphics_manager_hwobj.save_scene_snapshot(beam_image_filename)

        self.bl_hwobj.diffractometer_hwobj.set_phase(\
             self.bl_hwobj.diffractometer_hwobj.PHASE_CENTRING, timeout = 30)

        self.ready_event.set()
        return result

    def align_beam_test(self):
        gevent.spawn(self.align_beam_test_task)

    def align_beam_test_task(self):
        """
        Align beam procedure:
        1. Store aperture position and take out the aperture
        2. Store slits position and open to max
        3. In a loop take snapshot and move motors
        4. Put back aperture
        """
        aperture_hwobj = self.bl_hwobj.beam_info_hwobj.aperture_hwobj
        slits_hwobj = self.bl_hwobj.beam_info_hwobj.slits_hwobj

        log = logging.getLogger("HWR")
        msg = "Starting beam align"
        progress_info = {"progress_total": 6,
                         "progress_msg": msg}
        log.debug("BeamlineTest: %s" % msg)
        self.emit("testProgress", (1, progress_info))

        # 1/6 Diffractometer in BeamLocation phase ---------------------------
        if self.bl_hwobj.diffractometer_hwobj.in_plate_mode():
            msg = "1/6 : Setting diffractometer in Transfer phase"
            progress_info["progress_msg"] = msg
            log.debug("BeamlineTest: %s" % msg)
            self.emit("testProgress", (2, progress_info))
            self.bl_hwobj.diffractometer_hwobj.set_phase(\
             self.bl_hwobj.diffractometer_hwobj.PHASE_TRANSFER, timeout = 60)
            with gevent.Timeout(10, Exception("Timeout waiting for Tranfer phase")):
               while self.bl_hwobj.diffractometer_hwobj.current_phase != \
                     self.bl_hwobj.diffractometer_hwobj.PHASE_TRANSFER:
                     gevent.sleep(0.1)
       
        msg = "1/6 : Setting diffractometer in BeamLocation phase"
        progress_info["progress_msg"] = msg
        log.debug("BeamlineTest: %s" % msg)
        self.emit("testProgress", (2, progress_info)) 
        self.bl_hwobj.diffractometer_hwobj.set_phase(\
             self.bl_hwobj.diffractometer_hwobj.PHASE_BEAM, timeout = 30)

        with gevent.Timeout(10, Exception("Timeout waiting for BeamLocation phase")):
           while self.bl_hwobj.diffractometer_hwobj.current_phase != \
                 self.bl_hwobj.diffractometer_hwobj.PHASE_BEAM:
                  gevent.sleep(0.1)

        self.bl_hwobj.fast_shutter_hwobj.openShutter()
        gevent.sleep(0.1)
        aperture_hwobj.set_out()

        active_mode, beam_size = self.get_focus_mode()

        # 2.1/6 Set transmission to 100% (unfocused) or 10% (double focused)
        # 2.2/6 Opening slits when unfocused mode
        # 2.3/6 Setting zoom 4 if unfocused and zoom 8 for focused mode

        if active_mode == "Unfocused":
            msg = "2.1/6 : Setting transmission to 100%"
            progress_info["progress_msg"] = msg
            log.debug("BeamlineTest: %s" % msg)
            self.emit("testProgress", (2, progress_info))

            self.bl_hwobj.transmission_hwobj.setTransmission(100)
            if slits_hwobj:
                msg = "2.2/6 : Opening slits to 1 x 1 mm"
                progress_info["progress_msg"] = msg
                log.debug("BeamlineTest: %s" % msg)
                self.emit("testProgress", (2, progress_info))

                hor_gap, ver_gap = slits_hwobj.get_gaps()
                slits_hwobj.set_gap('Hor', 1)
                slits_hwobj.set_gap('Ver', 1)
            self.bl_hwobj.diffractometer_hwobj.set_zoom("Zoom 4")
        else:
            msg = "2/6 : Setting transmission to 10%"
            progress_info["progress_msg"] = msg
            log.debug("BeamlineTest: %s" % msg)
            self.emit("testProgress", (2, progress_info))           

            self.bl_hwobj.transmission_hwobj.setTransmission(10)
            self.bl_hwobj.diffractometer_hwobj.set_zoom("Zoom 8")
       
        self.align_beam_task() 
   
        # 5/6 For unfocused mode setting slits to 0.1 x 0.1 mm ---------------
        if active_mode == "Unfocused":
            msg = "5/6 : Setting slits to 0.1 x 0.1 mm%"
            progress_info["progress_msg"] = msg
            log.debug("BeamlineTest: %s" % msg)
            self.emit("testProgress", (5, progress_info)) 

            slits_hwobj.set_gap('Hor', 0.1)
            slits_hwobj.set_gap('Ver', 0.1)

        # 6/6 Update position of the beam mark position ----------------------
        msg = "6/6 : Updating beam mark position"
        progress_info["progress_msg"] = msg
        log.debug("BeamlineTest: %s" % msg)
        self.emit("testProgress", (6, progress_info))
        self.graphics_manager_hwobj.move_beam_mark_auto()

    def align_beam_task(self):
        """
        """

        log = logging.getLogger("HWR")
        msg = ""
        progress_info = {"progress_total": 6,
                         "progress_msg": msg}
        
        # 3.1/6 If energy < 10: set all lenses in ----------------------------
        crl_used = False 
        if self.bl_hwobj._get_energy() < 10:
            msg = "3.1/6 : Energy under 10keV. Setting all CRL lenses in"
            progress_info["progress_msg"] = msg
            log.debug("BeamlineTest: %s" % msg)
            self.emit("testProgress", (3, progress_info)) 
            crl_used = True
            crl_value = self.crl_hwobj.get_crl_value()
            self.crl_hwobj.set_crl_value([1, 1, 1, 1, 1, 1], timeout = 10)

        # 3.2/6 Pitch scan ---------------------------------------------------
        msg = "3/6 : Starting pitch scan"
        progress_info["progress_msg"] = msg
        log.debug("BeamlineTest: %s" % msg)
        self.emit("testProgress", (3, progress_info))
        self.cmd_start_pitch_scan(1)
        gevent.sleep(2.0)

        while self.scan_status != 0 :
           gevent.sleep(0.1)
        self.cmd_set_vmax_pitch(1)

        # 3.3/6 If crl used then set previous position -----------------------
        if crl_used:
            msg = "3.3/6 : Setting CRL lenses to previous position"
            progress_info["progress_msg"] = msg
            log.debug("BeamlineTest: %s" % msg)
            self.emit("testProgress", (3, progress_info))
            self.crl_hwobj.set_crl_value(crl_value, timeout = 10)

        self.bl_hwobj.diffractometer_hwobj.wait_device_ready(30)
        active_mode, beam_size = self.get_focus_mode()

        # 4/6 Applying Perp and Roll2nd correction ---------------------------
        if active_mode == "Unfocused":
            msg = "4/6 : Applying Perp and Roll2nd correction"
            progress_info["progress_msg"] = msg
            log.debug("BeamlineTest: %s" % msg)
            self.emit("testProgress", (4, progress_info))

        for i in range(3):
            with gevent.Timeout(10, Exception("Timeout waiting for beam shape")):
               beam_pos_displacement = [None, None]
               while None in beam_pos_displacement:
                   beam_pos_displacement = self.graphics_manager_hwobj.get_beam_displacement()
                   gevent.sleep(0.1)

               active_mode, beam_size = self.get_focus_mode()
               if active_mode == "Unfocused":
                   delta_hor = beam_pos_displacement[0] * self.scale_hor
                   delta_ver = beam_pos_displacement[1] * self.scale_ver
                   log.debug("BeamAlign: Applying %.3f mm horizontal and %.3f mm vertical correction" % \
                             (delta_hor, delta_ver))
                   self.vertical_motor_hwobj.moveRelative(delta_ver, wait=True)
                   self.horizontal_motor_hwobj.moveRelative(delta_hor, wait=True)

    def pitch_scan_status_changed(self, status):
        """
        """
        self.scan_status = status

    def test_autocentring(self):
        """
        Descript. :
        """
        result = {}
        result["result_bit"] = True
        result["result_details"] = []
        result["result_details"].append("Before autocentring<br>")

        beam_image_filename = os.path.join(self.test_source_directory,
                                           "auto_centring_before.png")
        self.graphics_manager_hwobj.save_scene_snapshot(beam_image_filename)
        result["result_details"].append("<img src=%s style=width:300px;><br>" % beam_image_filename)

        self.bl_hwobj.diffractometer_hwobj.start_centring_method(\
             self.bl_hwobj.diffractometer_hwobj.CENTRING_METHOD_AUTO, wait=True)

        result["result_details"].append("After autocentring<br>")
        beam_image_filename = os.path.join(self.test_source_directory,
                                           "auto_centring_after.png")
        self.graphics_manager_hwobj.save_scene_snapshot(beam_image_filename)
        result["result_details"].append("<img src=%s style=width:300px;><br>" % beam_image_filename)

        self.ready_event.set()
        return result
 

    def test_summary(self):
        """
        Descript. :
        """
        result = {}
        result["result_bit"] = True
        result["result_details"] = []
        table_cells = []

        for tine_prop in self['tine_props']:
            prop_names = eval(tine_prop.getProperty("prop_names"))
            if isinstance(prop_names, str):
                cell_str_list = []
                cell_str_list.append(tine_prop.getProperty("prop_device"))
                cell_str_list.append(prop_names)
                cell_str_list.append(str(tine.get(tine_prop.getProperty("prop_device"), prop_names)))
                table_cells.append(cell_str_list)
            else:
                for index, property_name in enumerate(prop_names):
                    cell_str_list = []
                    if index == 0:
                        cell_str_list.append(tine_prop.getProperty("prop_device"))
                    else:
                        cell_str_list.append("")
                    cell_str_list.append(property_name)
                    cell_str_list.append(str(tine.get(tine_prop.getProperty("prop_device"), property_name)))
                    table_cells.append(cell_str_list)                    
 
        result["result_details"] = SimpleHTML.create_table(\
             ["Context/Server/Device", "Property", "Value"],
             table_cells)
        self.ready_event.set()
        return result

    def test_focusing(self): 
        """
        Descript. :
        """
        result = {}
        result["result_details"] = []

        active_mode, beam_size = self.get_focus_mode()
        if active_mode is None:
            result["result_bit"] = False
            result["result_short"] = "No focusing mode detected"
        else:
            result["result_bit"] = True
            result["result_short"] = "%s mode detected" % active_mode

        focus_modes = self.get_focus_mode_names()
        focus_motors_list = self.get_focus_motors()

        table_cells = []
        if focus_motors_list:
            for motor in focus_motors_list:
                table_row = []
                table_row.append(motor['motorName'])
                for focus_mode in focus_modes:
                    res = (focus_mode in motor['focMode'])
                    table_row.append("<td bgcolor=%s>%.3f/%.3f</td>" % (\
                         TEST_COLORS_TABLE[res],
                         motor['focusingModes'][focus_mode], 
                         motor['position']))                        
                table_cells.append(table_row)
        
        focus_modes = ["Motors"] + list(focus_modes)
        result["result_details"] = SimpleHTML.create_table(\
              focus_modes, table_cells)
        self.ready_event.set()
        return result

    def measure_intensity(self):
        self.start_test_queue(["measure_intensity"])
        #gevent.spawn(self.measure_intensity_task)

    def test_measure_intensity(self):
        """
        """
        result = {}
        result["result_bit"] = True
        result["result_details"] = []

        current_phase = self.bl_hwobj.diffractometer_hwobj.current_phase 

        # 1. close guillotine and fast shutter --------------------------------
        self.bl_hwobj.collect_hwobj.close_guillotine(wait=True)
        self.bl_hwobj.fast_shutter_hwobj.closeShutter(wait=True)
        gevent.sleep(0.1)        

        #2. move back light in, check beamstop position -----------------------
        self.bl_hwobj.back_light_hwobj.move_in()

        beamstop_position = self.bl_hwobj.beamstop_hwobj.get_position()
        if beamstop_position == "BEAM":
            self.bl_hwobj.beamstop_hwobj.set_position("OFF") 
            self.bl_hwobj.diffractometer_hwobj.wait_device_ready(30)

        #3. check scintillator position --------------------------------------
        scintillator_position = self.bl_hwobj.\
            diffractometer_hwobj.get_scintillator_position() 
        if scintillator_position == "SCINTILLATOR":
            self.bl_hwobj.diffractometer_hwobj.\
                 set_scintillator_position("PHOTODIODE")
            self.bl_hwobj.diffractometer_hwobj.\
                 wait_device_ready(30)

        #5. open the fast shutter --------------------------------------------
        self.bl_hwobj.fast_shutter_hwobj.openShutter(wait=True)
        gevent.sleep(0.3)

        #6. measure mean intensity
        self.ampl_chan_index = 0

        if True:
            intens_value = self.chan_intens_mean.getValue()  
            intens_range_now = self.chan_intens_range.getValue()
            for intens_range in self.intensity_ranges:
                if intens_range['index'] is intens_range_now:
                    self.intensity_value = intens_value[self.ampl_chan_index] - intens_range['offset']
                    break
        
        #7. close the fast shutter -------------------------------------------
        self.bl_hwobj.fast_shutter_hwobj.closeShutter(wait=True)

        # 7/7 set back original phase ----------------------------------------
        self.bl_hwobj.diffractometer_hwobj.set_phase(current_phase)
        
        #8. Calculate --------------------------------------------------------  
        energy = self.bl_hwobj._get_energy()
        detector_distance = self.bl_hwobj.detector_hwobj.get_distance()
        beam_size = self.bl_hwobj.collect_hwobj.get_beam_size()
        transmission = self.bl_hwobj.transmission_hwobj.getAttFactor()

        result["result_details"].append("Energy: %.4f keV<br>" % energy)
        result["result_details"].append("Detector distance: %.2f mm<br>" % \
              detector_distance)
        result["result_details"].append("Beam size %.2f x %.2f mm<br>" % \
              (beam_size[0], beam_size[1]))
        result["result_details"].append("Transmission %.2f%%<br><br>" % \
              transmission)

        meas_item = [datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                     "%.4f" % energy,
                     "%.2f" % detector_distance, 
                     "%.2f x %.2f" % (beam_size[0], beam_size[1]), 
                     "%.2f" % transmission]

        air_trsm =  numpy.exp(-self.air_absorption_coeff_per_meter(energy) * \
             detector_distance / 1000.0)
        carb_trsm = self.carbon_window_transmission(energy)
        flux = 0.624151 * 1e16 * self.intensity_value / \
               self.diode_calibration_amp_per_watt(energy) / \
               energy / air_trsm / carb_trsm
        dose_rate = 1e-3 * 1e-14 * self.dose_rate_per_10to14_ph_per_mmsq(energy) * \
               flux / beam_size[0] / beam_size[1]  

        self.bl_hwobj.collect_hwobj.machine_info_hwobj.set_flux(flux)

        msg = "Flux = %1.1e photon/s" % flux
        result["result_details"].append(msg + "<br>")
        logging.getLogger("user_level_log").info(msg)
        result["result_short"] = msg
        meas_item.append("%1.1e" % flux)

        msg = "Dose rate =  %1.1e KGy/s" % dose_rate
        result["result_details"].append(msg + "<br>")
        logging.getLogger("user_level_log").info(msg)
        meas_item.append("%1.1e" % dose_rate)

        msg = "Time to reach 20 MGy = %d s = %d frames " % \
              (20000. / dose_rate, int(25 * 20000. / dose_rate))
        result["result_details"].append(msg + "<br><br>")
        logging.getLogger("user_level_log").info(msg)
        meas_item.append("%1.1e s, %d frames" % \
              (20000. / dose_rate, int(25 * 20000. / dose_rate)))

        self.intensity_measurements.insert(0, meas_item)
        result["result_details"].extend(SimpleHTML.create_table(\
             ["Time", "Energy (keV)", "Detector distance (mm)", "Beam size (mm)",
              "Transmission (%%)", "Flux (photons/s)", "Dose rate (KGy/s)",
              "Time to reach 20 MGy (sec, frames)"], self.intensity_measurements))

        self.ready_event.set()
        return result

    def stop_comm_process(self):
        """
        Descript. :
        """
        if self.current_test_procedure:
            self.current_test_procedure.kill()  
            self.ready_event.set()

    def get_available_tests(self):
        """
        Descript. :
        """
        return self.available_tests_dict

    def get_startup_test_list(self):
        """
        Descript. :
        """
        test_list = []
        for test in self.startup_test_list:
            if TEST_DICT.get(test):
                test_list.append(TEST_DICT[test]) 
        return test_list

    def generate_html_report(self):
        """
        Descript. :
        """
        html_filename = os.path.join(\
           self.test_directory,
           self.test_filename)
        archive_filename = os.path.join(\
           self.test_directory,
           datetime.now().strftime("%Y_%m_%d_%H") + "_" + \
           self.test_filename)

        try:
            output_file = open(html_filename, "w") 
            output_file.write(SimpleHTML.create_html_start("Beamline test summary"))
            output_file.write("<h1>Beamline %s Test results</h1>" % self.beamline_name)

            output_file.write("<h2>Executed tests:</h2>")
            table_cells = []
            for test in self.results_list:
                table_cells.append(["bgcolor=%s" % TEST_COLORS_TABLE[test["result_bit"]],
                                   "<a href=#%s>%s</a>" % (test["short_name"], test["full_name"]), 
                                   test["result_short"],
                                   test["start_time"],
                                   test["end_time"]])
           
            table_rec = SimpleHTML.create_table(\
                ["Name", "Result", "Start time", "End time"], 
                table_cells)
            for row in table_rec:
                output_file.write(row)
            output_file.write("\n<hr>\n")
         
            for test_result in self.results_html_list:
                output_file.write(test_result + "\n")
      
            output_file.write(SimpleHTML.create_html_end())
            output_file.close()
 
            self.emit("htmlGenerated", html_filename)
            logging.getLogger("HWR").info(\
               "BeamlineTest: Test result written in file %s" % html_filename)
        except:
            logging.getLogger("HWR").error(\
               "BeamlineTest: Unable to generate html report file %s" % html_filename)

        if self.arhive_results:
            try: 
                output_file = open(html_filename, "r")
                archive_file = open(archive_filename, "w")

                for line in output_file.readlines():
                    archive_file.write(line)
                output_file.close()
                archive_file.close()

                logging.getLogger("HWR").info("Archive file :%s generated" % \
                       archive_filename)
            except:
                logging.getLogger("HWR").error("BeamlineTest: Unable to " +\
                       "generate html report file %s" % archive_filename)
           
    def get_result_html(self):
        """
        Descript. :
        """
        html_filename = os.path.join(self.test_directory, self.test_filename)
        if os.path.exists(html_filename):
            return html_filename
 
    def generate_pdf_report(self, pdf_filename):
        """
        Descript. :
        """
        return
