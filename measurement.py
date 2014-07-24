__author__ = 'DAC_User'
import time
import logging
import os
from functools import partial

from epics import caput, caget, PV, camonitor, camonitor_clear

logging.basicConfig()
logger = logging.getLogger()
logger.setLevel(logging.DEBUG)

from xps_trajectory.xps_trajectory import XPSTrajectory

HOST = '164.54.160.34'
GROUP_NAME = 'G1'
POSITIONERS = "STX STZ STY OM"
DEFAULT_ACCEL = [0.5, 0.5, 0.5, 0.5]

GATHER_OUTPUTS = ('CurrentPosition', 'FollowingError',
                  'SetpointPosition', 'CurrentVelocity')


def collect_step_data(detector_position_x, detector_position_z, omega_start, omega_end, omega_step, exposure_time, x, y,
                      z, pv_names):
    # performs the actual step measurement
    # prepare the stage:
    prepare_stage(detector_position_x, detector_position_z, omega_start, pv_names, x, y, z)

    #prepare the detector
    previous_shutter_mode = prepare_detector(pv_names)

    #perform measurements:
    num_steps = (omega_end - omega_start) / omega_step
    print(num_steps)

    stage_xps = XPSTrajectory(host=HOST, group=GROUP_NAME, positioners=POSITIONERS)
    stage_xps.define_line_trajectories_general(stop_values=[[0, 0, 0, omega_step]], scan_time=exposure_time,
                                               pulse_time=0.1)

    for dummy_ind in range(int(num_steps)):
        t1 = time.time()

        logger.info('Running Omega-Trajectory: {} degree {} s'.format(omega_step, exposure_time))
        perform_step_collection(exposure_time, stage_xps, pv_names)
        print('Time needed {}.'.format(time.time() - t1))

    caput(pv_names['detector'] + ':ShutterMode', previous_shutter_mode)
    logger.info('Wide data collection finished.\n')

    del stage_xps


def perform_step_collection(exposure_time, stage_xps, pv_names):
    detector_checker = MarCCDChecker(pv_names['detector'])

    # start data collection
    collect_data(exposure_time + 50, pv_names)
    time.sleep(0.5)
    stage_xps.run_line_trajectory_general()

    #stop detector
    caput('13MARCCD2:cam1:Acquire', 0)
    #wait for readout
    while not detector_checker.is_finished():
        time.sleep(0.001)
    del detector_checker


def prepare_stage(detector_position_x, detector_pos_z, omega_start, pv_names, x, y, z):
    move_to_sample_pos(x, y, z, pv_names)
    move_to_omega_position(omega_start, pv_names)
    move_to_detector_position(detector_position_x, detector_pos_z, pv_names)


def prepare_detector(pv_names):
    previous_shutter_mode = caget(pv_names['detector'] + ':ShutterMode')
    caput(pv_names['detector'] + ':ShutterMode', 0)
    return previous_shutter_mode


def collect_wide_data(detector_position_x, detector_position_z, omega_start, omega_end, exposure_time, x, y, z,
                      pv_names):
    # performs the actual wide measurement

    # prepare the stage:
    prepare_stage(detector_position_x, detector_position_z, omega_start, pv_names, x, y, z)

    #prepare the detector
    previous_shutter_mode = prepare_detector(pv_names)
    detector_checker = MarCCDChecker(pv_names['detector'])

    #start data collection
    collect_data(exposure_time + 50, pv_names)

    #start trajectory scan
    omega_range = omega_end - omega_start
    run_omega_trajectory(omega_range, exposure_time)

    #stop detector and wait for the detector readout
    time.sleep(0.1)
    caput('13MARCCD2:cam1:Acquire', 0)
    caput(pv_names['detector'] + ':ShutterMode', previous_shutter_mode)
    while not detector_checker.is_finished():
        time.sleep(0.01)
    logger.info('Wide data collection finished.\n')
    return


class MarCCDChecker(object):
    def __init__(self, pv_name):
        self.detector_status = self.StatusChecker(3)
        camonitor(pv_name + ':MarReadoutStatus_RBV',
                  writer=partial(self.detector_status.set_status, 0, 'Idle', True))
        camonitor(pv_name + ':MarCorrectStatus_RBV',
                  writer=partial(self.detector_status.set_status, 1, 'Idle', True))
        camonitor(pv_name + ':MarWritingStatus_RBV',
                  writer=partial(self.detector_status.set_status, 2, 'Idle', True))

    def is_finished(self):
        if self.detector_status.is_true():
            camonitor_clear('13MARCCD2:cam1:MarReadoutStatus_RBV')
            camonitor_clear('13MARCCD2:cam1:MarCorrectStatus_RBV')
            camonitor_clear('13MARCCD2:cam1:MarWritingStatus_RBV')
            return True
        else:
            return False

    class StatusChecker(object):
        def __init__(self, num_status, value=False):
            self.status = []
            for ind in range(num_status):
                self.status.append(False)

        def set_status(self, ind, check_str, value, status_str):
            if status_str.split()[-1] == check_str:
                self.status[ind] = value

        def is_true(self):
            for status in self.status:
                if status is False:
                    return False
            return True


def run_omega_trajectory(omega, running_time):
    stage_xps = XPSTrajectory(host=HOST, group=GROUP_NAME, positioners=POSITIONERS)
    stage_xps.define_line_trajectories_general(stop_values=[[0, 0, 0, omega]], scan_time=running_time, pulse_time=0.1,
                                               accel_values=DEFAULT_ACCEL)

    logger.info("Running Omega-Trajectory: {}d {}s".format(omega, running_time))
    stage_xps.run_line_trajectory_general()
    del stage_xps


def collect_single_data(detector_position, exposure_time, x, y, z, omega, pv_names):
    # performs an actual single angle measurement:
    move_to_sample_pos(x, y, z, pv_names)
    move_to_omega_position(omega, pv_names)
    move_to_detector_position(detector_position, pv_names)
    collect_data(exposure_time, pv_names, wait=True)
    return


def move_to_sample_pos(x, y, z, pv_names, wait=True, callbacks=[]):
    logger.info('Moving Sample to x: {}, y: {}, z: {}'.format(x, y, z))
    motor_x = PV(pv_names['sample_position_x'])
    motor_y = PV(pv_names['sample_position_y'])
    motor_z = PV(pv_names['sample_position_z'])
    motor_x.put(x, use_complete=True)
    motor_y.put(y, use_complete=True)
    motor_z.put(z, use_complete=True)

    if wait:
        while not motor_x.put_complete and \
                not motor_y.put_complete and \
                not motor_z.put_complete:
            time.sleep(0.1)
        for callback in callbacks:
            callback()
    time.sleep(0.5)
    logger.info('Moving Sample to x: {}, y: {}, z: {} finished.\n'.format(x, y, z))
    return


def move_to_omega_position(omega, pv_names, wait=True):
    logger.info('Moving Sample Omega to {}'.format(omega))
    caput(pv_names['sample_position_omega'], omega, wait=wait)
    if wait:
        logger.info('Moving Sample Omega to {} finished.\n'.format(omega))


def move_to_detector_position(detector_position_x, detector_position_z, pv_names):
    logger.info('Moving Detector X to {}'.format(detector_position_x))
    caput(pv_names['detector_position_x'], detector_position_x, wait=True, timeout=300)
    logger.info('Moving Detector Z to {}'.format(detector_position_z))
    caput(pv_names['detector_position_z'], detector_position_z, wait=True, timeout=300)
    logger.info('Moving Detector finished. \n')


def collect_data(exposure_time, pv_names, wait=False):
    caput(pv_names['detector'] + ':AcquireTime', exposure_time)
    logger.info('Start data collection.')
    caput(pv_names['detector'] + ':Acquire', 1, wait=wait, timeout=exposure_time + 20)
    if wait:
        logger.info('Finished data collection.\n')


if __name__ == '__main__':
    pv_names = {'detector_position_x': '13IDD:m8',
                'detector_position_y': '13IDD:m84',
                'detector': '13MARCCD2:cam1',
                'sample_position_x': '13IDD:m81',
                'sample_position_y': '13IDD:m83',
                'sample_position_z': '13IDD:m82',
                'sample_position_omega': '13IDD:m96',
    }

    # collect_step_data(filename='/dac/temp',
    # detector_position=-333,
    #                   exposure_time=0.5,
    #                   x=-1.5, y=-1.5, z=-1.5,
    #                   omega_start=-93,
    #                   omega_end=-87,
    #                   omega_step=0.5,
    #                   pv_names=pv_names)

    # collect_single_data(filename='/dac/temp2',
    # detector_position=-333,
    # exposure_time=2,
    # x=-3, y=1.5, z=-3,
    # omega=-90,
    #                     pv_names=pv_names)

    run_omega_trajectory(5, 20)