import sys
sys.path.append('/Users/elemire/Workspace/caldaia_root/caldaia')
import utils.mysql_utils as mu
import utils.orm.lims_assemble_params_orm as lapo
import utils.orm.lims_plate_orm as lpo
import utils.orm.assay_plates_orm as ap_orm
import os
import argparse
import setup_logger
import logging
import assemble
import prism_metadata
import assemble_core

pod_dir = '/cmap/obelix/pod/custom'
logger = logging.getLogger(setup_logger.LOGGER_NAME)
default_config_filepath = os.path.expanduser('~/.prism_pipeline.cfg')


def build_parser():

    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    # The only required argument for automationify is -det_plate
    parser.add_argument("-det_plate", "-det", help="name of the prism replicate that is being processed",
                        type=str, required=True)
    parser.add_argument("-host", help="server to connect to", type=str, default='localhost')
    parser.add_argument("-config_filepath", "-cfg", help="mapping of analytes to pools and davepools",
                        type=str, default = default_config_filepath)
    parser.add_argument("-custom_map_path", '-pod', help="Custom path to map file", type=str, default=None)
    parser.add_argument("-custom_outfile_path", '-out', help="Custom outfile path", type=str, default=None)
    parser.add_argument("-verbose", '-v', help="Whether to print a bunch of output", action="store_true", default=False)
    parser.add_argument("-ignore_assay_plate_barcodes", "-batmanify", help="list of assay plate barcodes that should be"
                        " ignored / excluded from the assemble", nargs="+", default=None)

    return parser


def query_db(cursor, det_plate):
    # Query database for necessary information. See caldaia/utils/orm/lims_assemble_params_orm.py
    my_lapo = lapo.get_LAP(cursor, det_plate)

    return my_lapo


def create_det_plate_plate_orm_mapping(my_lapo, cursor):

    det_plate_to_orm_mapping = {}

    for det_plate in my_lapo.det_plate_list:

        my_lpo = lpo.get_by_det_plate(cursor, det_plate)

        det_plate_to_orm_mapping[det_plate] = my_lpo

    return det_plate_to_orm_mapping


def construct_plate_map_path(map_path, my_lapo):
    '''
    Use proj_id to get pod directory and pert plate name to get map file name.
    '''
    if map_path == None:
        map_path = os.path.join(pod_dir, my_lapo.project_id, "map_src", my_lapo.pert_plate + ".src")
    else:
        map_path = os.path.join(map_path, my_lapo.pert_plate + ".src")

    return map_path


def construct_davepool_csv_path_pairs(det_plate_orm_map, my_lapo):
    '''
    Using project ID, prism replicate name, and list of connected davepools, construct paths to csv for each davepool.
    Concatenate davepool IDs and csv filepaths into a single string for passing to assemble as an arg.
    :param my_lapo:
    :return: dp csv pairs string
    '''
    # We're going to make a list which we will then convert to a string
    dlist = []

    for det_plate in det_plate_orm_map:
        davepool = det_plate_orm_map[det_plate].davepool
        csv_path = os.path.join(pod_dir, my_lapo.project_id, 'lxb', det_plate, det_plate + '.csv')
        dlist.append((davepool, csv_path))

    return dlist


def construct_outfile_path(my_lapo, custom_outfile, prism_replicate_name):
    '''
    Check if assemble directory exists. If it does not, create it. The construct outfile path.
    :param my_lapo:
    :return: outfile string
    '''
    if custom_outfile is not None:
        outdir = custom_outfile
    else:
         outdir = os.path.join(pod_dir, my_lapo.project_id, 'assemble',
                           prism_replicate_name)
    if not os.path.exists(outdir):
        os.makedirs(outdir)

    return outdir

# put default in arg builder

def build_assay_plates(det_plate_orm_mapping, davepool_data_objects, ignore_assay_plate_barcodes, cursor):
    '''
    read all assay plate meta data NOT from  file at plates_mapping_path but rather from the LIMS database.
    All informaation that would originally be put in the plate tracking file is now in the plate_assay_plate table.
    We query this table using the name of the det plate.
    :param config_filepath:
    :param davepool_data_objects:
    :param ignore_assay_plate_barcodes:
    :return:
    '''

    # Assay plates will be a list of assay plate objects associated with these det plates. det_plate_davepool_data_objects_map has det_plates as keys and corresponding dpdos as values.
    assay_plates = []
    det_plate_davepool_data_objects_map = {}

    # build a mapping between det_plate name and davepool data objects
    for dpdo in davepool_data_objects:
        for det_plate in det_plate_orm_mapping:
            if det_plate_orm_mapping[det_plate].davepool == dpdo.davepool_id:
                det_plate_davepool_data_objects_map[det_plate] = dpdo

    for det_plate in det_plate_orm_mapping:
        machine_barcode = det_plate_orm_mapping[det_plate].machine_barcode
        det_plate_assay_plates = ap_orm.get_assay_plates(cursor, machine_barcode)
        assay_plates.extend(det_plate_assay_plates)

    logger.info("len(assay_plates):  {}".format(len(assay_plates)))

    logger.info("det_plate_davepool_data_objects_map.keys():  {}".format(det_plate_davepool_data_objects_map.keys()))

    # Add scan time to assay_plate metadata, and indicate if the assay plate should be ignored
    for ap in assay_plates:
        ap.det_plate_scan_time = det_plate_davepool_data_objects_map[ap.det_plate].csv_datetime
        ap.ignore = ap.assay_plate_barcode in ignore_assay_plate_barcodes


    return assay_plates


def main(args):
    '''
    Query database, use returned values to construct all assemble args and put into a list.
    :param det_plate:
    :return: Raw arguments as dictionary. Keys in dict correspond to form names in flask app.
    '''

    # Open Connection
    db = mu.DB(host=args.host).db
    cursor = db.cursor()

    # Uses lims_assemble_params_orm to query the lims database.
    my_lapo = query_db(cursor, args.det_plate)

    det_plate_orm_map = create_det_plate_plate_orm_mapping(my_lapo, cursor)

    # Make the path to the plate map
    map_path = construct_plate_map_path(args.custom_map_path, my_lapo)

    # Read all perturbagens form plate map file
    all_perturbagens = prism_metadata.build_perturbagens_from_file(map_path, prism_metadata.plate_map_type_CMap,
                                                                   args.config_filepath)

    # This returns a list of tuples, davepool and csv path.
    dp_csv_list = construct_davepool_csv_path_pairs(det_plate_orm_map, my_lapo)

    # Construct davepool data objects using your list of tuples.
    davepool_data_objects = assemble.read_davepool_data_objects(dp_csv_list)


    # Sets ignore assay plates list to an empty set if the argument is None (which it is by default)
    args.ignore_assay_plate_barcodes = set(
        args.ignore_assay_plate_barcodes) if args.ignore_assay_plate_barcodes is not None else set()

    # Build assay plates by querying the db prism_assay_plate table.
    assay_plates = build_assay_plates(det_plate_orm_map, davepool_data_objects, args.ignore_assay_plate_barcodes, cursor)

    # Use function in assemble to build row metadata
    prism_cell_list = assemble.build_prism_cell_list(args.config_filepath, assay_plates, my_lapo.cell_set_definition_file, my_lapo.davepool_mapping_file)

    #TODO add this to the database
    prism_replicate_name = my_lapo.pert_plate + '_' + my_lapo.prism_cellset_name + '_' + my_lapo.replicate

    # If not provided with a custom outfile, this will construct one using the plate info.
    outfile = construct_outfile_path(my_lapo, args.custom_outfile_path, prism_replicate_name)

    # Assemble using objects is the second half of assemble, taking all the python objects and combining them togethr
    assemble_core.main(prism_replicate_name, outfile, all_perturbagens, davepool_data_objects,
                       prism_cell_list)

    db.close()

    return os.path.join(outfile, prism_replicate_name + "_MEDIAN.gct")


if __name__ == "__main__":
    args = build_parser().parse_args(sys.argv[1:])
    setup_logger.setup(verbose=args.verbose)

    logger.debug("args:  {}".format(args))

    main(args)

