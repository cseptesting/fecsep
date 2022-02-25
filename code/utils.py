#python libraries
import numpy
import multiprocessing as mp
import pandas
import mercantile
import shapely.geometry
from functools import partial
import itertools

#pyCSEP libraries
from csep.core.regions import CartesianGrid2D, compute_vertices
from csep.core.forecasts import GriddedForecast
from csep.utils.plots import plot_spatial_dataset
from csep.models import Polygon
from csep.core.regions import QuadtreeGrid2D, geographical_area_from_bounds


def plot_matrix_comparative_test(evaluation_results, plot_args=None):
    """ Produces matrix plot for comparative tests for all forecasts

        Args:
            evaluation_results (list of result objects): paired t-test results
            plot_args (dict): plotting arguments for function

        Returns:
            ax (matplotlib.Axes): handle for figure
    """
    pass


def plot_binary_consistency_test(evaluation_result, plot_args=None):
    """ Plots consistency test result for binary evaluations

        Note: We might be able to recycle poisson here, but lets wrap it

        Args:
            evaluation_results (list of result objects): paired t-test results
            plot_args (dict): plotting arguments for function

        Returns:
            ax (matplotlib.Axes): handle for figure
    """
    pass


def global_region(dh=0.1, name="global", magnitudes=None):
    """ Creates a global region used for evaluating gridded forecasts on the global scale.

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
    coords = itertools.product(lons,lats)
    region = CartesianGrid2D([Polygon(bbox) for bbox in compute_vertices(coords, dh)], dh, name=name)
    if magnitudes is not None:
        region.magnitudes = magnitudes
    return region


def resample_block_model(model_path, resample_path, k):
    """

    Creates a resampled version of a model for code testing purposes

    :param model_path: Original model
    :param resample_path: Path to resampled model
    :param k: Grouping number of cells, creating blocks (k times k). Must be factor of 3600 and 1800

    """
    db = pandas.read_csv(model_path, header=0, sep=' ', escapechar='#')
    data = db.to_numpy()

    with open(model_path, 'r') as model:                                    # Read the magnitude columns in the forecast
        header = model.readline()[2:]
        magnitudes = [float(i) for i in header.split(' ')[6:]]

    nx = 3600
    ny = 1800
    nm = len(magnitudes)

    if nx % k != 0 or ny % k != 0:
        raise Exception('Grouping factor k must be factor of 3600 and 1800')

    ordered = data[:, 6:].reshape((nx, ny, nm))
    resampled = ordered.reshape(int(nx/k), k, int(ny/k), k, nm).sum(axis=(1, 3))  # blocks, n, blocks, n
    rates = resampled.reshape(int(nx/k) * int(ny/k), nm)

    region = global_region(0.1 * k)
    origin = region.origins()

    cells = numpy.vstack((origin[:, 0], origin[:, 0] + region.dh,
                          origin[:, 1], origin[:, 1] + region.dh,
                          numpy.zeros(int(nx * ny / k**2)), 70 * numpy.ones(int(nx * ny / k**2)))).T

    new_array = numpy.hstack((cells, rates))
    header = 'lon_min lon_max lat_min lat_max depth_min depth_max ' + ' '.join([str(i) for i in magnitudes])

    numpy.savetxt(resample_path, new_array, fmt=6 * ['%.1f'] + 31 * ['%.16e'], header=header)


def resample_models(k=20):


    """
    Resamples all forecast to low resolution for code testing purposes

    :param k: resample factor
    :return:
    """

    model_original = '../models/GEAR1_csep.txt'
    model_resampled = '../models/GEAR_resampled.txt'
    resample_block_model(model_original, model_resampled, k=k)

    model_original = '../models/KJSS_csep.txt'
    model_resampled = '../models/KJSS_resampled.txt'
    resample_block_model(model_original, model_resampled, k=k)

    model_original = '../models/SHIFT2F_GSRM_csep.txt'
    model_resampled = '../models/SHIFT2F_GSRM_resampled.txt'
    resample_block_model(model_original, model_resampled, k=k)

    model_original = '../models/TEAMr_csep.txt'
    model_resampled = '../models/TEAMr_resampled.txt'
    resample_block_model(model_original, model_resampled, k=k)

    model_original = '../models/WHEELr_csep.txt'
    model_resampled = '../models/WHEELr_resampled.txt'
    resample_block_model(model_original, model_resampled, k=k)


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


def prepare_forecast(model_path, time_horizon, dh=0.1, name=None, **kwargs):
    """ Returns a forecast from a time-independent model

        Note: For the time-independent global models the rates should be 'per year'

        Args:
            model_path (str): filepath of model
            time_horizon (float): time horizon of forecast in years     # todo < Should this be a pair of datetimes instead of the scale? In such way, the forecast object has time bounds, and can be identified with a catalog.
            dh (float): spatial cell size
            name (str): name of the model
            **kwargs: other keyword arguments

        Returns:
            forecast (GriddedForecast): pycsep forecast object with rates scaled to time horizon
    """

    if name is None:                                                        # Get name from file if none is provided
        name = model_path.split('_csep.txt')[0].split('/')[-1]

    print(f'Loading Forecast {name}')

    db = pandas.read_csv(model_path, header=0, sep=' ', escapechar='#')
    data = db.to_numpy()
    with open(model_path, 'r') as model:                                    # Read the magnitude columns in the forecast
        magnitudes = [float(i) for i in model.readline().split(' ')[7:]]   # todo check it works with escapechar #

    region = global_region(dh)             #todo: Hard coded here, but should be eventually able to read the region? e.g test italy using gear
    rates = data[:, 6:]

    forecast = GriddedForecast(data=rates, region=region, magnitudes=magnitudes, name=name, **kwargs)
    forecast.scale(time_horizon)
    print(f'\t Total {forecast.event_count:.4f} events forecasted in {time_horizon:.2f} years')

    return forecast


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
                                                                                 to define QuadTree forecasts
     """

    data = numpy.genfromtxt(csv_fname, dtype='str', delimiter=',')
    quadkeys = data[1:, 0]
    mws = data[0, 3:].astype(float)
    rates = data[1:, 3:]
    rates = rates.astype(float)
    region = QuadtreeGrid2D.from_quadkeys(quadkeys, magnitudes=mws)

    return rates, region, mws


def aggregate_quadtree_forecast(cart_forecast, quadtree_region):
    """ Aggregates conventional forecast onto quadtree region

        Args:
            cart_forecast (GriddedForecast): gridded forecast with regular grid
            quadtree_region (QuadtreeRegion2D): desired quadtree region

        Returns:
            qt_forecast (GriddedForecast): gridded forecast on quadtree grid
    """
    pass


def geographical_area_from_qk(quadk):

    """
    #--------------- Forecast mapping from one grid to another ----------

    Wrapper around function geographical_area_from_bounds
    """
    bounds = tile_bounds(quadk)
    return geographical_area_from_bounds(bounds[0], bounds[1], bounds[2], bounds[3])


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
    return shapely.geometry.Polygon([(fg[0], fg[1]), (fg[2], fg[1]), (fg[2], fg[3]), (fg[0], fg[3])])


def calc_cell_area(cell):
    """
    Required for parallel processing
    """
    return geographical_area_from_bounds(cell[0], cell[1], cell[2], cell[3])


def _map_overlapping_cells(fcst_grid_poly, fcst_cell_area, fcst_rate_poly, target_poly):  # ,
    """
    This functions work for Cells that do not directly conside with target polygon cells
    This function uses 3 variables, i.e. fcst_grid_poly, fcst_cell_area, fcst_rate_poly

    This function takes 1 target polygon, upon which forecasts are to be mapped. Finds all the cells of forecast grid that
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
            shared_area = geographical_area_from_bounds(intersect.bounds[0], intersect.bounds[1], intersect.bounds[2],
                                                        intersect.bounds[3])
            map_rate = map_rate + (fcst_rate_poly[j] * (shared_area / fcst_cell_area[j]))
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
    c = numpy.logical_and(numpy.logical_and(fcst_grid[:, 0] >= boundary[0], fcst_grid[:, 1] >= boundary[1]),
                          numpy.logical_and(fcst_grid[:, 2] <= boundary[2], fcst_grid[:, 3] <= boundary[3]))

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
    Inputs:
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

    if ncpu==None:
        ncpu = mp.cpu_count()
        pool = mp.Pool(ncpu)
    else:
        pool = mp.Pool(ncpu)  # mp.cpu_count()
    print('Number of CPUs :',ncpu)

    func_exact = partial(_map_exact_inside_cells, fcst_grid, fcst_rate)
    exact_rate = pool.map(func_exact, [poly for poly in target_grid])
    pool.close()

    exact_cells = []
    exact_rate_tgt = []
    for i in range(len(exact_rate)):
        exact_cells.append(exact_rate[i][1][0])
        exact_rate_tgt.append(exact_rate[i][0])

    exact_cells = numpy.concatenate(exact_cells)
    print('Number of Exact Cells: ', len(exact_cells))
    # Exclude all those cells from Grid that have already fallen entirely inside any cell of Target Grid
    fcst_rate_poly = numpy.delete(fcst_rate, exact_cells, axis=0)
    lft_fcst_grid = numpy.delete(fcst_grid, exact_cells, axis=0)

    #play now only with those cells are overlapping with multiple target cells
    ##Get the polygon of Remaining Forecast grid Cells
    pool = mp.Pool(ncpu)
    fcst_grid_poly = pool.map(create_polygon, [i for i in lft_fcst_grid])
    pool.close()

    # Get the Cell Area of forecast grid
    pool = mp.Pool(ncpu)
    fcst_cell_area = pool.map(calc_cell_area, [i for i in lft_fcst_grid])
    pool.close()

    #print('Calculate target polygons')
    pool = mp.Pool(ncpu)
    target_grid_poly = pool.map(create_polygon, [i for i in target_grid])
    pool.close()

    #print('--2nd Step: Start Polygon mapping--')
    pool = mp.Pool(ncpu)
    func_overlapping = partial(_map_overlapping_cells, fcst_grid_poly, fcst_cell_area, fcst_rate_poly)
    rate_tgt = pool.map(func_overlapping, [poly for poly in target_grid_poly])  # Uses above three Global Parameters
    pool.close()

    zero_pad_len = numpy.shape(fcst_rate)[1]
    for i in range(len(rate_tgt)):
        if len(rate_tgt[i]) < zero_pad_len:
            rate_tgt[i] = numpy.zeros(zero_pad_len)

    map_rate = numpy.add(rate_tgt, exact_rate_tgt)

    return map_rate


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
    data_mapped_bounds = _forecast_mapping_generic(bounds_target, bounds, data, ncpu=ncpu)
    target_forecast = GriddedForecast(data=data_mapped_bounds, region=target_grid,
                                          magnitudes=forecast_gridded.magnitudes)
    return target_forecast