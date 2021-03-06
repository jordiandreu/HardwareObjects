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
EMBLCRL
"""

import math
import gevent
import logging
from HardwareRepository.BaseHardwareObjects import HardwareObject


__author__ = "Ivars Karpics"
__credits__ = ["MXCuBE colaboration"]
__version__ = "2.2."


class EMBLCRL(HardwareObject):
    """
    Descript. :
    """

    def __init__(self, name):
        """
        Descript. :
        """
        HardwareObject.__init__(self, name)   

        self.focal_length = None
        self.lens_count = None

        self.modes = None
        self.current_mode = None
        self.energy_value = None
        self.energy_state = None
        self.current_focusing_mode = None
        self.crl_value = None
        self.chan_crl_value = None
        self.cmd_set_crl_value = None
        self.cmd_set_trans_value = None

        self.energy_hwobj = None
        self.beam_focusing_hwobj = None

        self.at_startup = None
           
    def init(self):
        """
        Descript. :
        """
        self.focal_length = self.getProperty("focal_length")
        self.lens_count = 6

        self.chan_crl_value = self.getChannelObject('chanCrlValue')
        if self.chan_crl_value: 
            self.chan_crl_value.connectSignal('update', self.crl_value_changed)

        self.cmd_set_crl_value = self.getCommandObject('cmdSetLenses')
        self.cmd_set_trans_value = self.getCommandObject('cmdSetTrans')

        self.energy_hwobj = self.getObjectByRole("energy")
        self.energy_value = self.energy_hwobj.getCurrentEnergy()
        if self.energy_hwobj:
            self.connect(self.energy_hwobj, 
                         "energyStateChanged", 
                         self.energy_state_changed)
        self.beam_focusing_hwobj = self.getObjectByRole("beam_focusing")
        self.connect(self.beam_focusing_hwobj,
                     "focusingModeChanged",
                     self.focusing_mode_changed)

        self.current_focusing_mode, beam_size = self.beam_focusing_hwobj.\
             get_active_focus_mode()
        self.focusing_mode_changed(self.current_focusing_mode, beam_size)

    def convert_value(self, value):
        """
        Descript. :
        """
        if type(value) in (list, tuple):
            lens_combination = 0
            for x in range(self.lens_count):
                lens_combination = lens_combination + value[x] * pow(2, x)
        else:
            lens_combination = [0, 0, 0, 0, 0, 0]
            for index in range(self.lens_count):
                lens_combination[index] = (value & pow(2, index)) / pow(2, index)

        return lens_combination

    def get_modes(self):
        """
        Descript. :
        """
        return self.beam_focusing_hwobj.get_available_lens_modes()

    def get_mode(self):
        """
        Descript. :
        """
        return self.current_mode

    def set_mode(self, mode):
        """
        Descript. :
        """
        self.current_mode = mode  
        if self.current_mode == "Out":
            self.set_crl_value([0, 0, 0, 0, 0, 0])
        elif self.current_mode == "Automatic":
            self.set_according_to_energy()
        self.emit('crlModeChanged', self.current_mode) 
 
    def energy_state_changed(self, state):
        """
        Descript. :
        """
        if state == self.energy_hwobj.READY and \
           state != self.energy_state:

            self.energy_value = self.energy_hwobj.getCurrentEnergy()
            if self.current_mode == "Automatic":
                self.set_according_to_energy()
        self.energy_state = state 

    def set_according_to_energy(self): 
        min_abs = 20
        selected_combination = None 
        #crl_value = [0, 0, 0, 0, 0, 0]

        self.energy_value = self.energy_hwobj.getCurrentEnergy()
        for combination_index in range(1, 65):
            current_abs = abs(self.energy_value - math.sqrt((2 * 341.52 * \
                combination_index) / (2000 * (1 / 42.6696 + 1 / self.focal_length))))
            if current_abs < min_abs:
                min_abs = current_abs
                selected_combination = combination_index
        #for index in range(6):
        #    crl_value[index] = (selected_combination & pow(2,index))/pow(2,index)
        self.set_crl_value(self.convert_value(selected_combination))

    def get_image_plane_distance(self, value):
        """
        Calculates image plane  
        """
        if type(value) == list: 
           lens_combination = self.convert_value(value)
           #lens_combination = 0
           #for x in range(6):
           #    lens_combination = lens_combination + value[x] * pow(2, x) 
        else:
           lens_combination = value  
        return 1. / (2 * 341.52 * lens_combination / 2000 /\
               (self.energy_value ** 2) - 1 / 42.6696)

    def focusing_mode_changed(self, focusing_mode, beam_size): 
        """
        Descript. :
        """
         
        if focusing_mode != None and self.at_startup:
            self.current_focusing_mode = focusing_mode
            self.modes = self.beam_focusing_hwobj.\
                get_available_lens_modes()
            self.set_mode(self.modes[0])
            self.set_crl_value(self.beam_focusing_hwobj.\
                get_lens_combination(self.current_focusing_mode))
        else:
            self.emit('crlValueChanged', None)
        self.at_startup = True

    def crl_value_changed(self, value):
        """
        Descript. :
        """
        self.crl_value = value
        self.emit('crlValueChanged', self.crl_value)

    def set_crl_value(self, value, timeout=None):
        """
        Sets CRL lens combination. If integer passed then
        converts value to list
        """
        if type(value) not in (list, tuple):
            value = self.convert_value(value)

        if value is not None:
           self.cmd_set_crl_value(value)
           self.cmd_set_trans_value(1)
        logging.getLogger("user_level_log").info("Setting CRL image plane " +\
           "distance to %.2f"%(self.get_image_plane_distance(value)))
        if timeout:
            gevent.sleep(1)
            with gevent.Timeout(10, Exception("Timeout waiting for CRL")):
               while value != self.crl_value:
                   gevent.sleep(0.1)  
               gevent.sleep(1)

    def get_crl_value(self):
        return self.crl_value

    def update_values(self):
        """
        Descript. :
        """
        self.emit('crlModeChanged', self.current_mode)
        self.emit('crlValueChanged', self.crl_value)

    def move_up(self):
        """
        Moves lense combination one value up
        """
        new_value = self.convert_value(self.crl_value) + 1
        self.set_crl_value(new_value)

    def move_down(self):
        """
        Moves lense combination one value down
        """
        new_value = self.convert_value(self.crl_value) - 1
        self.set_crl_value(new_value)

