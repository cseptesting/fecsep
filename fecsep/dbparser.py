import h5py
import pandas
import argparse, os
import numpy
import xml.etree.ElementTree as et
import itertools
from csep.models import Polygon
from csep.core.regions import QuadtreeGrid2D, CartesianGrid2D


def load_from_hdf5(filename):
    with h5py.File(filename, 'r') as db:
        rates = db['rates'][:]
        # todo check memory efficiency. Is it better to leave db open for multiple time intervals?
        magnitudes = db['magnitudes'][:]

        if 'quadkeys' in db.keys():
            region = QuadtreeGrid2D.from_quadkeys(
                db['quadkeys'][:].astype(str), magnitudes=magnitudes)
            region.get_cell_area()
        else:
            dh = db['dh'][:]
            bboxes = db['bboxes'][:]
            poly_mask = db['poly_mask'][:]
            region = CartesianGrid2D(
                [Polygon(bbox) for bbox in bboxes], dh, mask=poly_mask)

    return rates, region, magnitudes


class HDF5Serializer:

    @staticmethod
    def quadtree(filename, hdf5_filename=None):
        """

        Args:
            *args:

        Returns:

        """

        if hdf5_filename is None:
            hdf5_filename = f'{os.path.splitext(filename)[0]}.hdf5'

        with open(filename, 'r') as file_:
            qt_header = file_.readline().split(',')
            fmts = [str] + [float] * (len(qt_header) - 1)
        qt_formats = {i: j for i, j in zip(qt_header, fmts)}
        data = pandas.read_csv(filename, header=0, dtype=qt_formats)

        quadkeys = [i.encode('ascii', 'ignore') for i in data.tile]
        m = numpy.array(data.keys()[3:]).astype(float)
        rates = data[m.astype(str)].to_numpy()

        with h5py.File(hdf5_filename, 'a') as hf:
            hf.require_dataset('rates', shape=rates.shape, dtype=float)
            hf['rates'][:] = rates
            hf.require_dataset('magnitudes', shape=m.shape, dtype=float)
            hf['magnitudes'][:] = m
            hf.require_dataset('quadkeys', shape=len(quadkeys), dtype='S16')
            hf['quadkeys'][:] = quadkeys

    @staticmethod
    def dat(filename, hdf5_filename=None):
        """
        from csep.load_ascii
        Args:
            *args:

        Returns:

        """

        if hdf5_filename is None:
            hdf5_filename = f'{os.path.splitext(filename)[0]}.hdf5'
        data = numpy.loadtxt(filename)
        all_polys = data[:, :4]
        all_poly_mask = data[:, -1]
        sorted_idx = numpy.sort(
            numpy.unique(all_polys, return_index=True, axis=0)[1],
            kind='stable')
        unique_poly = all_polys[sorted_idx]
        poly_mask = all_poly_mask[sorted_idx]
        all_mws = data[:, -4]
        sorted_idx = numpy.sort(numpy.unique(all_mws, return_index=True)[1],
                                kind='stable')
        mws = all_mws[sorted_idx]
        bboxes = numpy.array(
            [tuple(itertools.product(bbox[:2], bbox[2:])) for bbox in
             unique_poly])
        dh = float(unique_poly[0, 3] - unique_poly[0, 2])

        n_mag_bins = len(mws)
        rates = data[:, -2].reshape(len(bboxes), n_mag_bins)

        with h5py.File(hdf5_filename, 'a') as hf:
            hf.require_dataset('rates', shape=rates.shape, dtype=float)
            hf['rates'][:] = rates
            hf.require_dataset('magnitudes', shape=mws.shape, dtype=float)
            hf['magnitudes'][:] = mws
            hf.require_dataset('bboxes', shape=bboxes.shape, dtype=float)
            hf['bboxes'][:] = bboxes
            hf.require_dataset('dh', shape=(1,), dtype=float)
            hf['dh'][:] = dh
            hf.require_dataset('poly_mask', shape=poly_mask.shape, dtype=float)
            hf['poly_mask'][:] = poly_mask

    @staticmethod
    def csv(filename, hdf5_filename=None):
        """
        from csep.load_ascii
        Args:
            *args:

        Returns:

        """

        def is_mag(num):
            try:
                m = float(num)
                if m > -1 and m < 12.:
                    return True
                else:
                    return False
            except ValueError:
                return False

        if hdf5_filename is None:
            hdf5_filename = f'{os.path.splitext(filename)[0]}.hdf5'
        with open(filename, 'r') as file_:
            line = file_.readline()
            if len(line.split(',')) > 3:
                sep = ','
            else:
                sep = ' '
        if 'tile' in line:
            HDF5Serializer.quadtree(filename, hdf5_filename=hdf5_filename)
            return

        data = pandas.read_csv(filename, header=0, sep=sep, escapechar='#',
                               skipinitialspace=True)

        data.columns = [i.strip() for i in data.columns]
        magnitudes = numpy.array([float(i) for i in data.columns if is_mag(i)])
        rates = data[[i for i in data.columns if is_mag(i)]].to_numpy()
        all_polys = data[
            ['lon_min', 'lon_max', 'lat_min', 'lat_max']].to_numpy()
        bboxes = numpy.array(
            [tuple(itertools.product(bbox[:2], bbox[2:])) for bbox in
             all_polys])
        dh = float(all_polys[0, 3] - all_polys[0, 2])

        try:
            poly_mask = data['mask']
        except:
            poly_mask = numpy.ones(bboxes.shape[0])

        with h5py.File(hdf5_filename, 'a') as hf:
            hf.require_dataset('rates', shape=rates.shape, dtype=float)
            hf['rates'][:] = rates
            hf.require_dataset('magnitudes', shape=magnitudes.shape,
                               dtype=float)
            hf['magnitudes'][:] = magnitudes
            hf.require_dataset('bboxes', shape=bboxes.shape, dtype=float)
            hf['bboxes'][:] = bboxes
            hf.require_dataset('dh', shape=(1,), dtype=float)
            hf['dh'][:] = dh
            hf.require_dataset('poly_mask', shape=poly_mask.shape, dtype=float)
            hf['poly_mask'][:] = poly_mask

    @staticmethod
    def xml(filename, hdf5_filename=None):
        """
        Parses a xml file (Italy experiment format) and drops into hdf5
        """
        if hdf5_filename is None:
            hdf5_filename = f'{os.path.splitext(filename)[0]}.hdf5'

        name = filename.split('.')[1]
        author = filename.split('.')[0].split('-')[0].capitalize()
        print('Processing model %s of author %s' % (name, author))
        tree = et.parse(filename)
        root = tree.getroot()

        data_Hij = []
        m_bins = []

        for children in list(root[0]):
            if 'modelName' in children.tag:
                name_xml = children.text
            elif 'author' in children.tag:
                author_xml = children.text
            elif 'forecastStartDate' in children.tag:
                start_date = children.text.replace('Z', '')
            elif 'forecastEndDate' in children.tag:
                end_date = children.text.replace('Z', '')
            elif 'defaultMagBinDimension' in children.tag:
                m_bin_width = float(children.text)
            elif 'lastMagBinOpen' in children.tag:
                lastmbin = float(children.text)
            elif 'defaultCellDimension' in children.tag:
                cell_dim = {i[0]: float(i[1]) for i in children.attrib.items()}
            elif 'depthLayer' in children.tag:
                depth = {i[0]: float(i[1]) for i in root[0][9].attrib.items()}
                cells = root[0][9]

        for cell in cells:
            cell_data = []
            m_cell_bins = []
            for i, m in enumerate(cell.iter()):
                if i == 0:
                    cell_data.extend([float(m.attrib['lon']),
                                      float(m.attrib['lat'])])
                else:
                    cell_data.append(float(m.text))
                    m_cell_bins.append(float(m.attrib['m']))
            data_Hij.append(cell_data)
            m_bins.append(m_cell_bins)
        try:
            data_Hij = numpy.array(data_Hij)
            m_bins = numpy.array(m_bins)
        except:
            raise Exception('Data is not square ')

        magnitudes = m_bins[0, :]
        rates = data_Hij[:, -len(magnitudes):]
        all_polys = numpy.vstack((data_Hij[:, 0] - cell_dim['lonRange'] / 2.,
                                  data_Hij[:, 0] + cell_dim['lonRange'] / 2.,
                                  data_Hij[:, 1] - cell_dim['latRange'] / 2.,
                                  data_Hij[:, 1] + cell_dim[
                                      'latRange'] / 2.)).T
        bboxes = numpy.array(
            [tuple(itertools.product(bbox[:2], bbox[2:])) for bbox in
             all_polys])
        dh = float(all_polys[0, 3] - all_polys[0, 2])
        poly_mask = numpy.ones(bboxes.shape[0])

        with h5py.File(hdf5_filename, 'a') as hf:
            hf.require_dataset('rates', shape=rates.shape, dtype=float)
            hf['rates'][:] = rates
            hf.require_dataset('magnitudes', shape=magnitudes.shape,
                               dtype=float)
            hf['magnitudes'][:] = magnitudes
            hf.require_dataset('bboxes', shape=bboxes.shape, dtype=float)
            hf['bboxes'][:] = bboxes
            hf.require_dataset('dh', shape=(1,), dtype=float)
            hf['dh'][:] = dh
            hf.require_dataset('poly_mask', shape=poly_mask.shape, dtype=float)
            hf['poly_mask'][:] = poly_mask


def serialize():
    parser = argparse.ArgumentParser()
    parser.add_argument("--format", help="format")
    parser.add_argument("--filename", help="Model forecast name")
    args = parser.parse_args()

    if args.format == 'quadtree':
        HDF5Serializer.quadtree(args.filename)
    if args.format == 'dat':
        HDF5Serializer.dat(args.filename)
    if args.format == 'csep' or args.format == 'csv':
        HDF5Serializer.csv(args.filename)
    if args.format == 'xml':
        HDF5Serializer.xml(args.filename)


if __name__ == '__main__':
    serialize()
