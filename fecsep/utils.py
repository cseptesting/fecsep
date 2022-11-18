# python libraries
import numpy
import re
import multiprocessing as mp
import os
import mercantile
import shapely.geometry
from functools import partial
import itertools
import functools
import yaml
import pandas
from matplotlib import pyplot
from matplotlib.lines import Line2D
import seaborn

# pyCSEP libraries
import six
import csep.core
import csep.utils
from csep.core.regions import CartesianGrid2D, compute_vertices
from csep.utils.plots import plot_spatial_dataset
from csep.models import Polygon
from csep.core.regions import QuadtreeGrid2D, geographical_area_from_bounds
from csep.utils.calc import cleaner_range

# feCSEP libraries

import fecsep.accessors
import fecsep.evaluations

_UNITS = ['years', 'months', 'weeks', 'days']
_PD_FORMAT = ['YS', 'MS', 'W', 'D']


def parse_csep_func(func):
    """
    Searchs in pyCSEP and feCSEP a function or method whose name matches the
    provided string.

    Args:
        func (str, obj) : representing the name of the pycsep/fecsep function
        or method

    Returns:
        The callable function/method object. If it was already callable,
        returns the same input
    """

    def __getattr__(self, item):
        return self[item]

    def rgetattr(obj, attr, *args):
        def _getattr(obj, attr):
            return getattr(obj, attr, *args)

        return functools.reduce(_getattr, [obj] + attr.split('.'))

    if callable(func):
        return func
    else:
        _target_modules = [csep,
                           csep.utils,
                           csep.utils.plots,
                           csep.core.regions,
                           fecsep.utils,
                           fecsep.accessors,
                           fecsep.evaluations]
        for module in _target_modules:
            try:
                return rgetattr(module, func)
            except AttributeError:
                pass
        raise AttributeError(
            f'Evaluation/Plot/Region function {func} has not yet been'
            f' implemented in fecsep or pycsep')


def parse_timedelta_string(window, exp_class='ti'):
    """
    Parses a float or string representing the testing time window length

    Note:
        Time-independent experiments defaults to `year` as time unit whereas
        time-dependent to `days`

    Args:
        window (str, int) : length of the time window
        exp_class (str) : experiment class

    Returns:
        Formatted :py:class:`str` representing the length and
        unit (year, month, week, day) of the time window

    """

    if isinstance(window, str):
        try:
            n, unit_ = [i for i in re.split(r'(\d+)', window) if i]
            unit = [i for i in [j[:-1] for j in _UNITS] if i in unit_.lower()][
                0]
            return f'{n}-{unit}s'

        except (ValueError, IndexError):
            raise ValueError('Time window is misspecified. '
                             'Try the amount followed by the time unit '
                             '(e.g. 1 day, 1 months, 3 years)')
    elif isinstance(window, float):
        n = window
        unit = 'year' if exp_class == 'ti' else 'day'
        return f'{n}-{unit}s'


def read_time_config(time_config, **kwargs):
    """
    Builds the temporal configuration of an experiment.

    Args:
        time_config (dict): Dictionary containing the explicit temporal
         attributes of the experiment (see `_attrs` local variable)
        **kwargs: Keywords related to _attrs are captured, in case they are
        passed explictly to an :fecsep:class:`Experiment` object

    Returns:
        A dictionary containing the experiment time attributes and the time
        windows to be evaluated

    """
    _attrs = ['start_date', 'end_date', 'intervals', 'horizon', 'offset',
              'growth', 'exp_class']

    if time_config is None:
        time_config = {}

    try:
        experiment_class = time_config.get('exp_class', kwargs['exp_class'])
    except KeyError:
        experiment_class = 'ti'
        time_config['exp_class'] = experiment_class

    time_config.update({i: j for i, j in kwargs.items() if i in _attrs})
    if 'horizon' in time_config.keys():
        time_config['horizon'] = parse_timedelta_string(time_config['horizon'])
    if 'offset' in time_config.keys():
        time_config['offset'] = parse_timedelta_string(time_config['offset'])

    if experiment_class == 'ti':
        time_config['time_windows'] = time_windows_ti(**time_config)
        return time_config
    elif experiment_class == 'td':
        time_config['time_windows'] = time_windows_td(**time_config)
        return time_config


def read_region_config(region_config, **kwargs):
    """
    Builds the region configuration of an experiment.

    Args:
        region_config (dict): Dictionary containing the explicit region
         attributes of the experiment (see `_attrs` local variable)
        **kwargs: Keywords related to _attrs are captured, in case they are
        passed explictly to an :fecsep:class:`Experiment` object

    Returns:
        A dictionary containing the region attributes of the experiment

    """
    _attrs = ['region', 'mag_min', 'mag_max', 'mag_bin', 'magnitudes',
              'depth_min', 'depth_max']

    if region_config is None:
        region_config = {}
    region_config.update({i: j for i, j in kwargs.items() if i in _attrs})
    dmin = region_config['depth_min']
    dmax = region_config['depth_max']
    depths = cleaner_range(dmin, dmax, dmax - dmin)

    magnitudes = region_config.get('magnitudes', None)
    if magnitudes is None:
        magmin = region_config['mag_min']
        magmax = region_config['mag_max']
        magbin = region_config['mag_bin']
        magnitudes = cleaner_range(magmin, magmax, magbin)

    region_data = region_config.get('region', None)
    try:
        region = parse_csep_func(region_data)() if region_data else None
    except AttributeError:
        if isinstance(region_data, str):
            with open(region_data, 'r') as file_:
                data = numpy.array([re.split(r'\s+|,', i.strip()) for i in
                                    file_.readlines()], dtype=float)
                region = CartesianGrid2D.from_origins(data, name=region_data)
        else:
            region = CartesianGrid2D.from_dict(region_data)

    region_config.update({'depths': depths,
                          'magnitudes': magnitudes,
                          'region': region})

    return region_config


def time_windows_ti(start_date=None,
                    end_date=None,
                    intervals=None,
                    horizon=None,
                    growth='incremental',
                    **_):
    """
    Creates the testing intervals for a time-independent experiment.

    Notes:
        The following arg combinations are possible:\n
        (start_date, end_date)\n
        (start_date, end_date, timeintervals)\n
        (start_date, end_date, timehorizon)\n
        (start_date, timeintervals, timehorizon)\n)

    Args:
        start_date (datetime.datetime): Start of the experiment
        end_date  (datetime.datetime): End of the experiment
        intervals (int): number of intervals to discretize the time span
        horizon (str): time length of each interval
        growth (str): incremental or cumulative time windows

    Returns:
        List of tuples containing the lower and upper boundaries of each
        testing window, as :py:class:`datetime.datetime`.

    """
    frequency = None

    if (intervals is None) and (horizon is None):
        intervals = 1
    elif horizon:
        print(horizon)
        n, unit = horizon.split('-')
        frequency = f'{n}{_PD_FORMAT[_UNITS.index(unit)]}'

    periods = intervals + 1 if intervals else intervals
    try:
        timelimits = pandas.date_range(start=start_date,
                                       end=end_date,
                                       periods=periods,
                                       freq=frequency).to_pydatetime()
    except ValueError as e_:
        print(e_)
        raise ValueError(
            'The following experiment parameters combinations are possible:\n'
            '   (start_date, end_date)\n'
            '   (start_date, end_date, intervals)\n'
            '   (start_date, end_date, timewindow)\n'
            '   (start_date, intervals, timewindow)\n')

    if growth == 'incremental':
        return [(i, j) for i, j in zip(timelimits[:-1],
                                       timelimits[1:])]

    elif growth == 'cumulative':
        return [(timelimits[0], i) for i in timelimits[1:]]


def time_windows_td(start_date=None,
                    end_date=None,
                    timeintervals=None,
                    timehorizon=None,
                    timeoffset=None,
                    **_):
    """
    Creates the testing intervals for a time-dependent experiment.

    Notes:
        The following arg combinations are possible:\n
        (start_date, end_date, timeintervals)\n
        (start_date, end_date, timehorizon)\n
        (start_date, timeintervals, timehorizon)\n
        (start_date,  end_date, timehorizon, timeoffset)\n
        (start_date,  timeinvervals, timehorizon, timeoffset)\n

    Args:
        start_date (datetime.datetime): Start of the experiment
        end_date  (datetime.datetime): End of the experiment
        timeintervals (int): number of intervals to discretize the time span
        timehorizon (str): time length of each time window
        timeoffset (str): Offset between consecutive forecast.
                          if None or timeoffset=timehorizon, windows are
                          non-overlapping

    Returns:
        List of tuples containing the lower and upper boundaries of each
        testing window, as :py:class:`datetime.datetime`.

    """

    frequency = None

    if timehorizon:
        n, unit = timehorizon.split('-')
        frequency = f'{n}{_PD_FORMAT[_UNITS.index(unit)]}'

    periods = timeintervals + 1 if timeintervals else timeintervals

    try:
        offset = timeoffset.split('-') if timeoffset else None
        start_offset = start_date + pandas.DateOffset(
            **{offset[1]: float(offset[0])}) if offset else start_date
        end_offset = end_date - pandas.DateOffset(
            **{offset[1]: float(offset[0])}) if offset else start_date

        lower_limits = pandas.date_range(start=start_date,
                                         end=end_offset,
                                         periods=periods,
                                         freq=frequency).to_pydatetime()[:-1]
        upper_limits = pandas.date_range(start=start_offset,
                                         end=end_date,
                                         periods=periods,
                                         freq=frequency).to_pydatetime()[:-1]
    except ValueError as e_:
        raise ValueError(
            'The following experiment parameters combinations are possible:\n'
            '   (start_date, end_date)\n'
            '   (start_date, end_date, intervals)\n'
            '   (start_date, end_date, timewindow)\n'
            '   (start_date, intervals, timewindow)\n')

    # if growth == 'incremental':
    #     timewindows = [(i, j) for i, j in zip(timelimits[:-1],
    #                                           timelimits[1:])]
    # elif growth == 'cumulative':
    #     timewindows = [(timelimits[0], i) for i in timelimits[1:]]

    # return timewindows


def plot_matrix_comparative_test(evaluation_results, p=0.05, order=True,
                                 plot_args=None):
    """ Produces matrix plot for comparative tests for all models

        Args:
            evaluation_results (list of result objects): paired t-test results
            plot_args (dict): plotting arguments for function

        Returns:
            ax (matplotlib.Axes): handle for figure
    """
    names = [i.sim_name for i in evaluation_results]

    T_value = numpy.array(
        [Tw_i.observed_statistic for Tw_i in evaluation_results]).T
    T_quantile = numpy.array(
        [Tw_i.quantile[0] for Tw_i in evaluation_results]).T
    W_quantile = numpy.array(
        [Tw_i.quantile[1] for Tw_i in evaluation_results]).T
    score = numpy.sum(T_value, axis=1) / T_value.shape[0]

    if order:
        arg_ind = numpy.flip(numpy.argsort(score))
    else:
        arg_ind = numpy.arange(len(score))

    data_t = T_value[arg_ind, :][:,
             arg_ind]  ## Flip rows/cols if ordered by value
    data_w = W_quantile[arg_ind, :][:, arg_ind]
    data_tq = T_quantile[arg_ind, :][:, arg_ind]
    fig, ax = pyplot.subplots(1, 1, figsize=(7, 6))

    cmap = seaborn.diverging_palette(220, 20, as_cmap=True)
    seaborn.heatmap(data_t, vmin=-3, vmax=3, center=0, cmap=cmap,
                    ax=ax, cbar_kws={'pad': 0.01, 'shrink': 0.7,
                                     'label': 'Information Gain',
                                     'anchor': (0., 0.)}),
    ax.set_yticklabels([names[i] for i in arg_ind], rotation='horizontal')
    ax.set_xticklabels([names[i] for i in arg_ind], rotation='vertical')
    for n, i in enumerate(data_tq):
        for m, j in enumerate(i):
            if j > 0 and data_w[n, m] < p:
                # ax.scatter(n + 0.5, m + 0.5, marker='o', s=75, facecolor='None', edgecolor='black')
                ax.scatter(n + 0.5, m + 0.5, marker='o', s=5, color='black')

    legend_elements = [Line2D([0], [0], marker='o', lw=0,
                              label='$\mathcal{T}$ and $\mathcal{W}$ significant',
                              markerfacecolor="black", markeredgecolor='black',
                              markersize=4)]
    fig.legend(handles=legend_elements, loc='lower right',
               bbox_to_anchor=(0.75, 0.0, 0.2, 0.2), handletextpad=0)
    pyplot.tight_layout()


def forecast_mapping(forecast_gridded, target_grid, ncpu=None):
    """
    Aggregates conventional forecast onto quadtree region
    This is generic function, which can map any forecast on to another grid.
    Wrapper function over "_forecat_mapping_generic"
    Forecast mapping onto Target Grid

    forecast_gridded: csep.core.forecast with other grid.
    target_grid: csep.core.region.CastesianGrid2D or QuadtreeGrid2D
    only_de-aggregate: Flag (True or False)
        Note: set the flag "only_deagregate = True" Only if one is sure that both grids are Quadtree and
        Target grid is high-resolution at every level than the other grid.
    """
    from csep.core.forecasts import GriddedForecast
    bounds_target = target_grid.bounds
    bounds = forecast_gridded.region.bounds
    data = forecast_gridded.data
    data_mapped_bounds = _forecast_mapping_generic(bounds_target, bounds, data,
                                                   ncpu=ncpu)
    target_forecast = GriddedForecast(data=data_mapped_bounds,
                                      region=target_grid,
                                      magnitudes=forecast_gridded.magnitudes)
    return target_forecast


def plot_quadtree_forecast(qtree_forecast):
    """
    Currently, only a single-resolution plotting capability is available. So we aggregate multi-resolution forecast on a single-resolution grid and then plot it

    Args: csep.core.models.GriddedForecast

    Returns: class:`matplotlib.pyplot.ax` object
    """
    quadkeys = qtree_forecast.region.quadkeys
    l = []
    for qk in quadkeys:
        l.append(len(qk))

    if l.count(l[0]) == len(l):
        # single-resolution grid
        ax = qtree_forecast.plot()
    else:
        print('Multi-resolution grid detected.')
        print(
            'Currently, we do not offer utility to plot a forecast with multi-resolution grid')
        print(
            'Therefore, forecast is being aggregated on a single-resolution grid (L8) for plotting')

        single_res_grid_L8 = QuadtreeGrid2D.from_single_resolution(8)
        forecast_L8 = forecast_mapping(qtree_forecast, single_res_grid_L8)
        ax = forecast_L8.plot()

    return ax


def europe_efehr20(dh_scale=1, magnitudes=None, name="europe_efehr20",
                   use_midpoint=True):
    """

    """
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    filepath = os.path.join(root_dir, 'fecsep', 'artifacts',
                            'europe_efehr20.csv')
    midpoints = numpy.genfromtxt(filepath, delimiter=',')
    europe_region = CartesianGrid2D.from_origins(midpoints,
                                                 magnitudes=magnitudes)

    return europe_region


class MarkdownReport:
    """ Class to generate a Markdown report from a study """

    def __init__(self, outname='results.md'):
        self.outname = outname
        self.toc = []
        self.has_title = True
        self.markdown = []

    def add_introduction(self, adict):
        """ Generate document header from dictionary """
        first = f"# CSEP Testing Results: {adict['simulation_name']}  \n" \
                f"**Forecast Name:** {adict['forecast_name']}  \n" \
                f"**Simulation Start Time:** {adict['origin_time']}  \n" \
                f"**Evaluation Time:** {adict['evaluation_time']}  \n" \
                f"**Catalog Source:** {adict['catalog_source']}  \n" \
                f"**Number Simulations:** {adict['num_simulations']}\n"

        # used to determine to place TOC at beginning of document or after introduction.
        self.has_introduction = True
        self.markdown.append(first)
        return first

    def add_text(self, text):
        """
        text should be a list of strings where each string will be on its own line.
        each add_text command represents a paragraph.
        Args:
            text (list): lines to write
        Returns:
        """
        self.markdown.append('  '.join(text) + '\n\n')

    def add_figure(self, title, relative_filepaths, level=2, ncols=3,
                   add_ext=False, text='', caption=''):
        """
        this function expects a list of filepaths. if you want the output stacked, select a
        value of ncols. ncols should be divisible by filepaths. todo: modify formatted_paths to work when not divis.
        Args:
            title: name of the figure
            level (int): value 1-6 depending on the heading
            relative_filepaths (str or List[Tuple[str]]): list of paths in order to make table
        Returns:
        """
        # verify filepaths have proper extension should always be png
        is_single = False
        paths = []
        if isinstance(relative_filepaths, six.string_types):
            is_single = True
            paths.append(relative_filepaths)
        else:
            paths = relative_filepaths

        correct_paths = []
        if add_ext:
            for fp in paths:
                correct_paths.append(fp + '.png')
        else:
            correct_paths = paths

        # generate new lists with size ncols
        formatted_paths = [correct_paths[i:i + ncols] for i in
                           range(0, len(paths), ncols)]

        # convert str into a proper list, where each potential row is an iter not str
        def build_header(row):
            top = "|"
            bottom = "|"
            for i, _ in enumerate(row):
                if i == ncols:
                    break
                top += " |"
                bottom += " --- |"
            return top + '\n' + bottom

        def add_to_row(row):
            if len(row) == 1:
                return f"![]({row[0]})"
            string = '| '
            for item in row:
                string = string + f' ![]({item}) |'
            return string

        level_string = f"{level * '#'}"
        result_cell = []
        locator = title.lower().replace(" ", "_")
        result_cell.append(
            f'{level_string} {title}  <a name="{locator}"></a>\n')
        result_cell.append(f'{text}\n')

        for i, row in enumerate(formatted_paths):
            if i == 0 and not is_single:
                result_cell.append(build_header(row))
            result_cell.append(add_to_row(row))
        result_cell.append('\n')
        result_cell.append(f'{caption}')
        self.markdown.append('\n'.join(result_cell) + '\n')

        # generate metadata for TOC
        self.toc.append((title, level, locator))

    def add_heading(self, title, level=1, text='', add_toc=True):
        # multipying char simply repeats it
        if isinstance(text, str):
            text = [text]
        cell = []
        level_string = f"{level * '#'}"
        locator = title.lower().replace(" ", "_")
        sub_heading = f'{level_string} {title} <a name="{locator}"></a>\n'
        cell.append(sub_heading)
        try:
            for item in list(text):
                cell.append(item)
        except:
            raise RuntimeWarning(
                "Unable to add document subhead, text must be iterable.")
        self.markdown.append('\n'.join(cell) + '\n')

        # generate metadata for TOC
        if add_toc:
            self.toc.append((title, level, locator))

    def add_list(self, list):
        cell = []
        for item in list:
            cell.append(f"* {item}")
        self.markdown.append('\n'.join(cell) + '\n')

    def add_title(self, title, text):
        self.has_title = True
        self.add_heading(title, 1, text, add_toc=False)

    def table_of_contents(self):
        """ generates table of contents based on contents of document. """
        if len(self.toc) == 0:
            return
        toc = ["# Table of Contents"]
        for title, level, locator in self.toc:
            space = '   ' * (level - 1)
            toc.append(f"{space}1. [{title}](#{locator})")
        insert_loc = 1 if self.has_title else 0
        self.markdown.insert(insert_loc, '\n'.join(toc) + '\n')

    def add_table(self, data, use_header=True):
        """
        Generates table from HTML and styles using bootstrap class
        Args:
           data List[Tuple[str]]: should be (nrows, ncols) in size. all rows should be the
                         same sizes
        Returns:
            table (str): this can be added to subheading or other cell if desired.
        """
        table = []
        table.append('<div class="table table-striped">')
        table.append(f'<table>')

        def make_header(row):
            header = []
            header.append('<tr>')
            for item in row:
                header.append(f'<th>{item}</th>')
            header.append('</tr>')
            return '\n'.join(header)

        def add_row(row):
            table_row = ['<tr>']
            for item in row:
                table_row.append(f"<td>{item}</td>")
            table_row.append('</tr>')
            return '\n'.join(table_row)

        for i, row in enumerate(data):
            if i == 0 and use_header:
                table.append(make_header(row))
            else:
                table.append(add_row(row))
        table.append('</table>')
        table.append('</div>')
        table = '\n'.join(table)
        self.markdown.append(table + '\n')

    def save(self, save_dir):
        output = list(itertools.chain.from_iterable(self.markdown))
        full_md_fname = os.path.join(save_dir, self.outname)
        with open(full_md_fname, 'w') as f:
            f.writelines(output)


class NoAliasLoader(yaml.Loader):
    def ignore_aliases(self):
        return True


def plot_forecast_lowres(forecast, plot_args, k=4):
    """
    Plot a reduced resolution plot. The forecast values are kept the same, but cells are enlarged
    :param forecast: GriddedForecast object
    :param plot_args: arguments to be passed to plot_spatial_dataset
    :param k: Resampling factor. Selects cells every k row and k columns.

    """

    print('\tPlotting Forecast')
    plot_args['title'] = forecast.name
    region = forecast.region
    coords = region.origins()
    dataset = numpy.log10(forecast.spatial_counts(cartesian=True))[::k, ::k]
    region.xs = numpy.unique(region.get_cartesian(coords[:, 0])[0, ::k])
    region.ys = numpy.unique(region.get_cartesian(coords[:, 1])[::k, 0])
    plot_spatial_dataset(dataset, region, set_global=True, plot_args=plot_args)


def quadtree_csv_loader(csv_fname):
    """ Load quadtree forecasted stored as csv file
        The format expects forecast as a comma separated file, in which first column corresponds to quadtree grid cell (quadkey).
        The second and thrid columns indicate depth range.
        The corresponding enteries in the respective row are forecast rates corresponding to the magnitude bins.
        The first line of forecast is a header, and its format is listed here:
            'Quadkey', depth_min, depth_max, Mag_0, Mag_1, Mag_2, Mag_3 , ....
             Quadkey is a string. Rest of the values are floats.
        For the purposes of defining region objects quadkey is used.
        We assume that the starting value of magnitude bins are provided in the header.
        Args:
            csv_fname: file name of csep forecast in csv format
        Returns:
            rates, region, mws (numpy.ndarray, QuadtreeRegion2D, numpy.ndarray): rates, region, and magnitude bins needed
                                                                                 to define QuadTree models
     """

    data = numpy.genfromtxt(csv_fname, dtype='str', delimiter=',')
    quadkeys = data[1:, 0]
    mws = data[0, 3:].astype(float)
    rates = data[1:, 3:]
    rates = rates.astype(float)
    region = QuadtreeGrid2D.from_quadkeys(quadkeys, magnitudes=mws)
    region.get_cell_area()

    return rates, region, mws


def geographical_area_from_qk(quadk):
    """
    Wrapper around function geographical_area_from_bounds
    """
    bounds = tile_bounds(quadk)
    return geographical_area_from_bounds(bounds[0], bounds[1], bounds[2],
                                         bounds[3])


def tile_bounds(quad_cell_id):
    """
    It takes in a single Quadkkey and returns lat,longs of two diagonal corners using mercantile
    Parameters
    ----------
    quad_cell_id : Stirng
        Quad key of a cell.

    Returns
    -------
    bounds : Mercantile object
        Latitude and Longitude of bottom left AND top right corners.

    """

    bounds = mercantile.bounds(mercantile.quadkey_to_tile(quad_cell_id))
    return [bounds.west, bounds.south, bounds.east, bounds.north]


def create_polygon(fg):
    """
    Required for parallel processing
    """
    return shapely.geometry.Polygon(
        [(fg[0], fg[1]), (fg[2], fg[1]), (fg[2], fg[3]), (fg[0], fg[3])])


def calc_cell_area(cell):
    """
    Required for parallel processing
    """
    return geographical_area_from_bounds(cell[0], cell[1], cell[2], cell[3])


def _map_overlapping_cells(fcst_grid_poly, fcst_cell_area, fcst_rate_poly,
                           target_poly):  # ,
    """
    This functions work for Cells that do not directly conside with target polygon cells
    This function uses 3 variables, i.e. fcst_grid_poly, fcst_cell_area, fcst_rate_poly

    This function takes 1 target polygon, upon which models are to be mapped. Finds all the cells of forecast grid that
    match with this polygon and then maps the forecast rate of those cells according to area.

    fcst_grid_polygon (variable in memory): The grid that needs to be mapped on target_poly
    fcst_rate_poly (variable in memory): The forecast that needs to be mapped on target grid polygon
    fcst_cell_area (variable in memory): The cell area of forecast grid

    Args:
        target_poly: One polygon upon which forecast grid is to be mapped.
    returns:
        The forecast rate received by target_poly
    """
    map_rate = numpy.array([0])
    for j in range(len(fcst_grid_poly)):
        # Iterates over ALL the cells of Forecast grid and find the cells that overlap with target cell (poly).
        if target_poly.intersects(fcst_grid_poly[j]):  # overlaps

            intersect = target_poly.intersection(fcst_grid_poly[j])
            shared_area = geographical_area_from_bounds(intersect.bounds[0],
                                                        intersect.bounds[1],
                                                        intersect.bounds[2],
                                                        intersect.bounds[3])
            map_rate = map_rate + (
                    fcst_rate_poly[j] * (shared_area / fcst_cell_area[j]))
    return map_rate


def _map_exact_inside_cells(fcst_grid, fcst_rate, boundary):
    """
    Uses 2 Global variables. fcst_grid, fcst_rate
    Takes a cell_boundary and finds all those fcst_grid cells that fit exactly inside of it
    And then sum-up the rates of all those cells fitting inside it to get forecast rate for boundary_cell

    Args:
        boundary: 1 cell with [lon1, lat1, lon2, lat2]
    returns:
        1 - sum of forecast_rates for cell that fall totally inside of boundary cell
        2 - Array of the corresponding cells that fall inside
    """
    c = numpy.logical_and(numpy.logical_and(fcst_grid[:, 0] >= boundary[0],
                                            fcst_grid[:, 1] >= boundary[1]),
                          numpy.logical_and(fcst_grid[:, 2] <= boundary[2],
                                            fcst_grid[:, 3] <= boundary[3]))

    exact_cells = numpy.where(c == True)

    return numpy.sum(fcst_rate[c], axis=0), exact_cells


def _forecast_mapping_generic(target_grid, fcst_grid, fcst_rate, ncpu=None):
    """
    This function can perofrmns both aggregation and de-aggregation/
    It is a wrapper function that uses 4 functions in respective order
    i.e. _map_exact_cells, _map_overlapping_cells, calc_cell_area, create_polygon

    Maps the forecast rates of one grid to another grid using parallel processing
    Works in two steps:
        1 - Maps all those cells that fall entirely on target cells
        2 - The cells that overlap with multiple cells, map them according to cell area
    Inumpyuts:
        target_grid: Target grid bounds, upon which forecast is to be mapped.
                        [n x 4] array, Bottom left and Top Right corners
                        [lon1, lat1, lon2, lat2]
        fcst_grid: Available grid that is available with forecast
                            Same as bounds_targets
        fcst_rate: Forecast rates to be mapped.
                    [n x mbins]

    Returns:
        target_rates:
                Forecast rates mapped on the target grid
                [nx1]
    """

    if ncpu == None:
        ncpu = mp.cpu_count()
        pool = mp.Pool(ncpu)
    else:
        pool = mp.Pool(ncpu)  # mp.cpu_count()
    print('Number of CPUs :', ncpu)

    func_exact = partial(_map_exact_inside_cells, fcst_grid, fcst_rate)
    exact_rate = pool.map(func_exact, [poly for poly in target_grid])
    pool.close()

    exact_cells = []
    exact_rate_tgt = []
    for i in range(len(exact_rate)):
        exact_cells.append(exact_rate[i][1][0])
        exact_rate_tgt.append(exact_rate[i][0])

    exact_cells = numpy.concatenate(exact_cells)
    # Exclude all those cells from Grid that have already fallen entirely inside any cell of Target Grid
    fcst_rate_poly = numpy.delete(fcst_rate, exact_cells, axis=0)
    lft_fcst_grid = numpy.delete(fcst_grid, exact_cells, axis=0)

    # play now only with those cells are overlapping with multiple target cells
    ##Get the polygon of Remaining Forecast grid Cells
    pool = mp.Pool(ncpu)
    fcst_grid_poly = pool.map(create_polygon, [i for i in lft_fcst_grid])
    pool.close()

    # Get the Cell Area of forecast grid
    pool = mp.Pool(ncpu)
    fcst_cell_area = pool.map(calc_cell_area, [i for i in lft_fcst_grid])
    pool.close()

    # print('Calculate target polygons')
    pool = mp.Pool(ncpu)
    target_grid_poly = pool.map(create_polygon, [i for i in target_grid])
    pool.close()

    # print('--2nd Step: Start Polygon mapping--')
    pool = mp.Pool(ncpu)
    func_overlapping = partial(_map_overlapping_cells, fcst_grid_poly,
                               fcst_cell_area, fcst_rate_poly)
    rate_tgt = pool.map(func_overlapping, [poly for poly in
                                           target_grid_poly])  # Uses above three Global Parameters
    pool.close()

    zero_pad_len = numpy.shape(fcst_rate)[1]
    for i in range(len(rate_tgt)):
        if len(rate_tgt[i]) < zero_pad_len:
            rate_tgt[i] = numpy.zeros(zero_pad_len)

    map_rate = numpy.add(rate_tgt, exact_rate_tgt)

    return map_rate


def _set_dockerfile(name):
    string = f"""
## Install Docker image from trusted source
FROM python:3.8.13

## Setup user args
ARG USERNAME={name}
ARG USER_UID=1100
ARG USER_GID=$USER_UID

RUN mkdir -p /usr/src/{name} && chown $USER_UID:$USER_GID /usr/src/{name} 
RUN groupadd --non-unique -g $USER_GID $USERNAME && useradd -u $USER_UID -g $USER_GID -s /bin/sh -m $USERNAME

## Set up work directory in the Docker container
WORKDIR /usr/src/{name}/

## Copy the files from the local machine (the repository) to the Docker container
COPY --chown=$USER_UID:$USER_GID . /usr/src/{name}/

## Calls setup.py, install python dependencies and install this model as a python module
ENV VIRTUAL_ENV=/venv/
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"

# RUN pip install --no-cache-dir --upgrade pip
# RUN pip install -r requirements.txt
RUN pip install numpy pandas h5py

USER $USERNAME

    """
    return string


def _global_region(dh=0.1, name="global", magnitudes=None):
    """ Creates a global region used for evaluating gridded models on the global scale.

    Modified from csep.core.regions.global_region

    The gridded region corresponds to the

    Args:
        dh:

    Returns:
        csep.utils.CartesianGrid2D:
    """
    # generate latitudes

    lons = numpy.arange(-180.0, 180, dh)
    lats = numpy.arange(-90, 90, dh)
    coords = itertools.product(lons, lats)
    region = CartesianGrid2D(
        [Polygon(bbox) for bbox in compute_vertices(coords, dh)], dh,
        name=name)
    if magnitudes is not None:
        region.magnitudes = magnitudes
    return region


def _check_zero_bins(exp, catalog, test_date):
    for model in exp.models:
        forecast = model.create_forecast(exp.start_date, test_date)
        catalog.filter_spatial(forecast.region)
        bins = catalog.get_spatial_idx()
        zero_forecast = numpy.argwhere(forecast.spatial_counts()[bins] == 0)
        if zero_forecast:
            print(zero_forecast)
        ax = catalog.plot(plot_args={'basemap': 'stock_img'})
        ax = forecast.plot(ax=ax, plot_args={'alpha': 0.8})
        ax.plot(catalog.get_longitudes()[zero_forecast.ravel()],
                catalog.get_latitudes()[zero_forecast.ravel()], 'o',
                markersize=10)
        pyplot.savefig(f'{model.path}/{model.name}.png', dpi=300)
    for model in exp.models:
        forecast = model.create_forecast(exp.start_date, test_date)
        catalog.filter_spatial(forecast.region)
        sbins = catalog.get_spatial_idx()
        mbins = catalog.get_mag_idx()
        zero_forecast = numpy.argwhere(forecast.data[sbins, mbins] == 0)
        print('event', 'cell', sbins[zero_forecast], 'datum',
              catalog.data[zero_forecast])
        if zero_forecast:
            print(zero_forecast)
            print('cellfc', forecast.get_longitudes()[sbins[zero_forecast]],
                  forecast.get_latitudes()[sbins[zero_forecast]])
            print('scounts', forecast.spatial_counts()[sbins[zero_forecast]])
            print('data', forecast.data[sbins[zero_forecast]])
            print(forecast.data[zero_forecast[0]])
        ax = catalog.plot(plot_args={'basemap': 'stock_img'})
        ax = forecast.plot(ax=ax, plot_args={'alpha': 0.8})
        ax.plot(catalog.get_longitudes()[zero_forecast.ravel()],
                catalog.get_latitudes()[zero_forecast.ravel()], 'o',
                markersize=10)
        pyplot.savefig(f'{model.path}/{model.name}.png', dpi=300)
