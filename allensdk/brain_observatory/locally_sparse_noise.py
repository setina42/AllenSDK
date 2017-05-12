# Copyright 2016-2017 Allen Institute for Brain Science
# This file is part of Allen SDK.
#
# Allen SDK is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# Allen SDK is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Allen SDK.  If not, see <http://www.gnu.org/licenses/>.

import logging
import allensdk.brain_observatory.stimulus_info as stimulus_info
import h5py
import numpy as np
import pandas as pd
import scipy.ndimage
from .receptive_field_analysis.receptive_field import get_receptive_field_data_dict_with_postprocessing
from .receptive_field_analysis.visualization import plot_receptive_field_data

from . import circle_plots as cplots
from . import observatory_plots as oplots
from .brain_observatory_exceptions import MissingStimulusException
from .stimulus_analysis import StimulusAnalysis
from .receptive_field_analysis.tools import dict_generator, read_h5_group
from scipy.stats.mstats import zscore

import matplotlib.pyplot as plt

class LocallySparseNoise(StimulusAnalysis):
    """ Perform tuning analysis specific to the locally sparse noise stimulus.

    Parameters
    ----------
    data_set: BrainObservatoryNwbDataSet object

    stimulus: string
       Name of locally sparse noise stimulus.  See brain_observatory.stimulus_info.

    nrows: int
       Number of rows in the stimulus template

    ncol: int
       Number of columns in the stimulus template
    """

    LSN_ON = 255
    LSN_OFF = 0
    LSN_GREY = 127
    LSN_OFF_SCREEN = 64

    def __init__(self, data_set, stimulus=None, **kwargs):
        super(LocallySparseNoise, self).__init__(data_set, **kwargs)
        if stimulus is None:
            self.stimulus = stimulus_info.LOCALLY_SPARSE_NOISE
        else:
            self.stimulus = stimulus

        try:
            lsn_dims = stimulus_info.LOCALLY_SPARSE_NOISE_DIMENSIONS[self.stimulus]
        except KeyError as e:
            raise KeyError("Unknown stimulus name: %s" % self.stimulus)
        
        self.nrows = lsn_dims[0]
        self.ncols = lsn_dims[1]
        
        self._LSN = LocallySparseNoise._PRELOAD
        self._LSN_mask = LocallySparseNoise._PRELOAD
        self._sweeplength = LocallySparseNoise._PRELOAD
        self._interlength = LocallySparseNoise._PRELOAD
        self._extralength = LocallySparseNoise._PRELOAD
        self._mean_response = LocallySparseNoise._PRELOAD
        self._receptive_field = LocallySparseNoise._PRELOAD
        self._cell_index_receptive_field_analysis_data_dict = LocallySparseNoise._PRELOAD

    @property
    def LSN(self):
        if self._LSN is LocallySparseNoise._PRELOAD:
            self.populate_stimulus_table()

        return self._LSN

    @property
    def LSN_mask(self):
        if self._LSN_mask is LocallySparseNoise._PRELOAD:
            self.populate_stimulus_table()

        return self._LSN_mask

    @property
    def sweeplength(self):
        if self._sweeplength is LocallySparseNoise._PRELOAD:
            self.populate_stimulus_table()

        return self._sweeplength

    @property
    def interlength(self):
        if self._interlength is LocallySparseNoise._PRELOAD:
            self.populate_stimulus_table()

        return self._interlength

    @property
    def extralength(self):
        if self._extralength is LocallySparseNoise._PRELOAD:
            self.populate_stimulus_table()

        return self._extralength

    @property
    def receptive_field(self):
        if self._receptive_field is LocallySparseNoise._PRELOAD:
            self._receptive_field = self.get_receptive_field()

        return self._receptive_field

    @property
    def cell_index_receptive_field_analysis_data_dict(self):
        if self._cell_index_receptive_field_analysis_data_dict is LocallySparseNoise._PRELOAD:
            self._cell_index_receptive_field_analysis_data_dict = self.get_receptive_field_analysis_data()

        return self._cell_index_receptive_field_analysis_data_dict

    @property
    def mean_response(self):
        if self._mean_response is LocallySparseNoise._PRELOAD:
            self._mean_response = self.get_mean_response()

        return self._mean_response


    def get_peak(self):
        LocallySparseNoise._log.info('Calculating peak response properties')

        peak = pd.DataFrame(index=range(self.numbercells), columns=('rf_center_on_x_lsn', 'rf_center_on_y_lsn',
                                                                    'rf_center_off_x_lsn', 'rf_center_off_y_lsn',
                                                                    'rf_area_on_lsn', 'rf_area_off_lsn',
                                                                    'rf_distance_lsn', 'rf_overlap_index_lsn',
                                                                    'rf_chi2_lsn',
                                                                    'cell_specimen_id'))
        csids = self.data_set.get_cell_specimen_ids()

        df = self.get_receptive_field_attribute_df()
        peak.cell_specimen_id = csids

        for nc in range(self.numbercells):
            peak['rf_chi2_lsn'].iloc[nc] = df['chi_squared_analysis/min_p'].iloc[nc]

            # find the index of the largest on subunit, if it exists
            area_on = df['on/gaussian_fit/area'].iloc[nc]
            on_i = np.argmax(area_on) if isinstance(area_on, np.ndarray) else None

            if on_i is None:
                peak['rf_area_on_lsn'].iloc[nc] = np.nan
                peak['rf_center_on_x_lsn'].iloc[nc] = np.nan
                peak['rf_center_on_y_lsn'].iloc[nc] = np.nan
            else:
                peak['rf_area_on_lsn'].iloc[nc] = df['on/gaussian_fit/area'].iloc[nc][on_i]
                peak['rf_center_on_x_lsn'].iloc[nc] = df['on/gaussian_fit/center_x'].iloc[nc][on_i]
                peak['rf_center_on_y_lsn'].iloc[nc] = df['on/gaussian_fit/center_y'].iloc[nc][on_i]

            # find the index of the largest off subunit, if it exists
            area_off = df['off/gaussian_fit/area'].iloc[nc]
            off_i = np.argmax(area_off) if isinstance(area_off, np.ndarray) else None

            if off_i is None:
                peak['rf_area_off_lsn'].iloc[nc] = np.nan
                peak['rf_center_off_x_lsn'].iloc[nc] = np.nan
                peak['rf_center_off_y_lsn'].iloc[nc] = np.nan
            else:
                peak['rf_area_off_lsn'].iloc[nc] = df['off/gaussian_fit/area'].iloc[nc][off_i]
                peak['rf_center_off_x_lsn'].iloc[nc] = df['off/gaussian_fit/center_x'].iloc[nc][off_i]
                peak['rf_center_off_y_lsn'].iloc[nc] = df['off/gaussian_fit/center_y'].iloc[nc][off_i]


            if on_i is not None and off_i is not None:
                peak['rf_distance_lsn'].iloc[nc] = df['on/gaussian_fit/distance'].iloc[nc][on_i][off_i]
                peak['rf_overlap_index_lsn'].iloc[nc] = df['on/gaussian_fit/overlap'].iloc[nc][on_i][off_i]
            else:
                peak['rf_distance_lsn'].iloc[nc] = np.nan
                peak['rf_overlap_index_lsn'].iloc[nc] = np.nan

        return peak

    def populate_stimulus_table(self):
        self._stim_table = self.data_set.get_stimulus_table(self.stimulus)
        self._LSN, self._LSN_mask = self.data_set.get_locally_sparse_noise_stimulus_template(
            self.stimulus, mask_off_screen=False)
        self._sweeplength = self._stim_table['end'][
            1] - self._stim_table['start'][1]
        self._interlength = 4 * self._sweeplength
        self._extralength = self._sweeplength


    def get_mean_response(self):
        logging.debug("Calculating mean responses")
        mean_response = np.empty(
            (self.nrows, self.ncols, self.numbercells + 1, 2))

        for xp in range(self.nrows):
            for yp in range(self.ncols):
                on_frame = np.where(self.LSN[:, xp, yp] == self.LSN_ON)[0]
                off_frame = np.where(self.LSN[:, xp, yp] == self.LSN_OFF)[0]
                subset_on = self.mean_sweep_response[
                    self.stim_table.frame.isin(on_frame)]
                subset_off = self.mean_sweep_response[
                    self.stim_table.frame.isin(off_frame)]
                mean_response[xp, yp, :, 0] = subset_on.mean(axis=0)
                mean_response[xp, yp, :, 1] = subset_off.mean(axis=0)
        return mean_response

    def get_receptive_field(self):
        ''' Calculates receptive fields for each cell
        '''

        receptive_field = np.zeros((self.nrows, self.ncols, self.numbercells, 2))

        for cell_index in range(len(self.cell_index_receptive_field_analysis_data_dict)):
            curr_receptive_field_data_dict = self.cell_index_receptive_field_analysis_data_dict[str(cell_index)]
            rf_on = curr_receptive_field_data_dict['on']['rts_convolution']['data'].copy()
            rf_off = curr_receptive_field_data_dict['off']['rts_convolution']['data'].copy()
            rf_on[np.logical_not(curr_receptive_field_data_dict['on']['fdr_mask']['data'].sum(axis=0))] = np.nan
            rf_off[np.logical_not(curr_receptive_field_data_dict['off']['fdr_mask']['data'].sum(axis=0))] = np.nan
            receptive_field[:,:,cell_index, 0] = rf_on
            receptive_field[:, :, cell_index, 1] = rf_off

        return receptive_field


    def get_receptive_field_analysis_data(self):
        ''' Calculates receptive fields for each cell
        '''

        csid_receptive_field_data_dict = {}
        for cell_index in range(self.data_set.number_of_cells):
            csid_receptive_field_data_dict[str(cell_index)] = get_receptive_field_data_dict_with_postprocessing(
                self.data_set, cell_index, self.stimulus, alpha=.05, number_of_shuffles=10000)

        return csid_receptive_field_data_dict


    def plot_receptive_field_analysis_data(self, cell_index, **kwargs):
        receptive_field_data_dict = self._cell_index_receptive_field_analysis_data_dict[str(cell_index)]
        return plot_receptive_field_data(receptive_field_data_dict, self, **kwargs)

    def get_receptive_field_attribute_df(self):

        df_list = []
        for cell_index_as_str, receptive_field_data_dict in self.cell_index_receptive_field_analysis_data_dict.items():

            attribute_dict = {}
            for x in dict_generator(receptive_field_data_dict):
                if x[-3] == 'attrs':
                    if len(x[:-3]) == 0:
                        key = x[-2]
                    else:
                        key = '/'.join(['/'.join(x[:-3]), x[-2]])
                    attribute_dict[key] = x[-1]

            massaged_dict = {}
            for key, val in attribute_dict.items():
                massaged_dict[key] = [val]

            massaged_dict['oeid'] = self.data_set.get_metadata()['ophys_experiment_id']

            curr_df = pd.DataFrame.from_dict(massaged_dict)
            df_list.append(curr_df)

            attribute_df = pd.concat(df_list)


        return attribute_df.sort_values(by='cell_index')

    @staticmethod
    def merge_mean_response(rc1, rc2):
        """ Move out of this class, to session analysis
        """

        # make sure that rc1 is the larger one
        if rc2.shape[0] > rc1.shape[0]:
            rc1, rc2 = rc2, rc1

        shape_mult = np.array(rc1.shape) / np.array(rc2.shape)

        rc2_zoom = scipy.ndimage.zoom(rc2, shape_mult, order=0)

        return rc1 + rc2_zoom

    def plot_cell_receptive_field(self, on, cell_specimen_id=None, color_map=None, clim=None, mask=None, cell_index=None):
        if color_map is None:
            color_map = 'Reds' if on else 'Blues'

        onst = 'on' if on else 'off'
        cell_idx = self.row_from_cell_id(cell_specimen_id, cell_index)
        rf_dict = self.cell_index_receptive_field_analysis_data_dict[str(cell_idx)]
        rts = rf_dict[onst]['rts']['data']
        rts[np.logical_not(rf_dict[onst]['fdr_mask']['data'].sum(axis=0))] = np.nan

        oplots.plot_receptive_field(rts, 
                                    color_map=color_map, 
                                    clim=clim, 
                                    mask=mask)

    def plot_population_receptive_field(self, color_map='RdPu', clim=None, mask=None):
        rf = np.nansum(self.receptive_field, axis=(2,3))
        oplots.plot_receptive_field(rf,
                                    color_map=color_map,
                                    clim=clim,
                                    mask=mask)

    def sort_trials(self):
        ds = self.data_set

        lsn_movie, lsn_mask = ds.get_locally_sparse_noise_stimulus_template(self.stimulus, 
                                                                            mask_off_screen=False)

        baseline_trials = np.unique(np.where(lsn_movie[:,-5:,-1] != LocallySparseNoise.LSN_GREY)[0])
        baseline_df = self.mean_sweep_response.ix[baseline_trials]
        cell_baselines = np.nanmean(baseline_df.values, axis=0)

        lsn_movie[:,~lsn_mask] = LocallySparseNoise.LSN_OFF_SCREEN

        trials = {}
        for row in range(self.nrows):
            for col in range(self.ncols):
                on_trials = np.where(lsn_movie[:,row,col] == LocallySparseNoise.LSN_ON)
                off_trials = np.where(lsn_movie[:,row,col] == LocallySparseNoise.LSN_OFF)

                trials[(col,row,True)] = on_trials
                trials[(col,row,False)] = off_trials

        return trials, cell_baselines


    def open_pincushion_plot(self, on, cell_specimen_id=None, color_map=None, cell_index=None):
        cell_index = self.row_from_cell_id(cell_specimen_id, cell_index)

        trials, baselines = self.sort_trials()
        data = self.mean_sweep_response[str(cell_index)].values
        
        cplots.make_pincushion_plot(data, trials, on, 
                                    self.nrows, self.ncols,
                                    clim=[ baselines[cell_index], data.mean() + data.std() * 3 ],
                                    color_map=color_map,
                                    radius=1.0/16.0)

    @staticmethod
    def from_analysis_file(data_set, analysis_file, stimulus):
        lsn = LocallySparseNoise(data_set, stimulus)

        lsn.populate_stimulus_table()

        if stimulus == stimulus_info.LOCALLY_SPARSE_NOISE:
            stimulus_suffix = stimulus_info.LOCALLY_SPARSE_NOISE_SHORT
        elif stimulus == stimulus_info.LOCALLY_SPARSE_NOISE_4DEG:
            stimulus_suffix = stimulus_info.LOCALLY_SPARSE_NOISE_4DEG_SHORT
        elif stimulus == stimulus_info.LOCALLY_SPARSE_NOISE_8DEG:
            stimulus_suffix = stimulus_info.LOCALLY_SPARSE_NOISE_8DEG_SHORT

        try:

            with h5py.File(analysis_file, "r") as f:
                k = "analysis/mean_response_%s" % stimulus_suffix
                if k in f:
                    lsn._mean_response = f[k].value

            lsn._sweep_response = pd.read_hdf(analysis_file, "analysis/sweep_response_%s" % stimulus_suffix)
            lsn._mean_sweep_response = pd.read_hdf(analysis_file, "analysis/mean_sweep_response_%s" % stimulus_suffix)

            with h5py.File(analysis_file, "r") as f:
                lsn._cell_index_receptive_field_analysis_data_dict = LocallySparseNoise.read_cell_index_receptive_field_analysis_dict(f, stimulus)

        except Exception as e:
            raise MissingStimulusException(e.args)

        return lsn

    @staticmethod
    def save_cell_index_receptive_field_analysis_dict(cell_index_receptive_field_analysis_data_dict, new_nwb, prefix):

        attr_list = []
        file_handle = h5py.File(new_nwb.nwb_file, 'a')
        if prefix in file_handle['analysis']:
            del file_handle['analysis'][prefix]
        f = file_handle.create_group('analysis/%s' % prefix)
        for x in dict_generator(cell_index_receptive_field_analysis_data_dict):
            if x[-2] == 'data':
                f['/'.join(x[:-1])] = x[-1]
            elif x[-3] == 'attrs':
                attr_list.append(x)
            else:
                raise Exception

        for x in attr_list:
            if len(x) > 3:
                f['/'.join(x[:-3])].attrs[x[-2]] = x[-1]
            else:
                assert len(x) == 3

                if x[-1] is None:
                    f.attrs[x[-2]] = np.NaN
                else:
                    f.attrs[x[-2]] = x[-1]

        file_handle.close()
        

    @staticmethod
    def read_cell_index_receptive_field_analysis_dict(file_handle, prefix, path=None):
        k = 'analysis/%s' % prefix
        if k in file_handle:
            f = file_handle['analysis/%s' % prefix]
            if path is None:
                receptive_field_data_dict = read_h5_group(f)
            else:
                receptive_field_data_dict = read_h5_group(f[path])

            return receptive_field_data_dict
        else:
            return None

            

