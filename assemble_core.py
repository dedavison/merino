import setup_logger
import logging
import sys
import os
import broadinstitute_cmap.io.GCToo.GCToo as GCToo
import validate_prism_gct
import prism_metadata
import pandas
import broadinstitute_cmap.io.GCToo.write_gctoo as write_gctoo

logger = logging.getLogger(setup_logger.LOGGER_NAME)

_remove_row_annotations = ["id", "ignore"]
_remove_col_annotations = ["assay_plate_barcode"]

_null = "-666"
_NaN = "NaN"

class DataByCell:
    def __init__(self, cell_data_map=None, well_list=None):
        self.cell_data_map = cell_data_map
        self.well_list = well_list
    def __str__(self):
        return "cell_data_map:  {}  well_list:  {}".format(self.cell_data_map, self.well_list)


def build_davepool_id_to_cells_map(prism_cell_list):
    '''
    build one-to-many mapping between davepool ID and the corresponding PRISM cell lines that are within that davepool
    :param prism_cell_list:
    :return:
    '''
    r = {}
    for pc in prism_cell_list:
        if pc.davepool_id not in r:
            r[pc.davepool_id] = []
        r[pc.davepool_id].append(pc)

    return r


def truncate_data_objects_to_plate_map(davepool_data_objects, all_perturbagens, truncate_to_platemap):
    '''
    There are some cases in which we are subsetting plates into different groups, ie. more than one gct per plate.
    This was the case for PPCN. As such, we need a function to truncate the data to match the plate map which is given.
    :param davepool_data_objects:
    :param all_perturbagens:
    :param truncate_to_platemap:
    :return:
    '''

    platemap_well_list = set([p.well_id for p in all_perturbagens])

    for davepool in davepool_data_objects:
        # Check that wells match. If so, return the data. If not, check if -trunc argument was used.
        if platemap_well_list == set(davepool.median_data.keys()):
            return davepool_data_objects
        # Truncate to platemap if true.
        elif truncate_to_platemap == True:
            for d in davepool_data_objects[0].median_data.keys():
                 if d not in platemap_well_list:
                     del davepool_data_objects[0].median_data[d]

            for c in davepool_data_objects[0].count_data.keys():
                if c not in platemap_well_list:
                    del davepool_data_objects[0].count_data[c]
        # Raise exception if not.
        else:
            raise Exception("Assemble truncate data objects to plate map: Well lists of platemap and csv do not match")


    return davepool_data_objects


def build_data_by_cell(cells, davepool_data_obj):
    cell_to_median_data_map = {}
    median_wells = []
    cell_to_count_data_map = {}
    count_wells = []

    l = [(cell_to_median_data_map, median_wells, davepool_data_obj.median_headers, davepool_data_obj.median_data),
        (cell_to_count_data_map, count_wells, davepool_data_obj.count_headers, davepool_data_obj.count_data)]

    for (cell_data_map, wells, headers, data) in l:
        cell_header_map = {}
        for c in cells:
            if c.ignore == False:
                cell_header_map[c] = headers.index(c.analyte_id)
            cell_data_map[c] = []

        for d in data.keys():
            wells.append(d)
            for c in cells:
                if c in cell_header_map:
                    datum_index = cell_header_map[c]
                    datum = data[d][datum_index - 1]
                else:
                    datum = float('nan')

                cell_data_map[c].append(datum)

    return (DataByCell(cell_to_median_data_map, median_wells), DataByCell(cell_to_count_data_map, count_wells))


def combine_maps_with_checks(source_map, dest_map):
    source_keys = set(source_map.keys())
    dest_keys = set(dest_map.keys())

    common_keys = source_keys & dest_keys

    if len(common_keys) > 0:
        msg = "the source_map and dest_map had common_keys:  {}".format(common_keys)
        logger.error(msg)
        raise Exception("assemble combine_maps_with_checks " + msg)
    else:
        dest_map.update(source_map)


def process_data(davepool_data_objects, davepool_id_to_cells_map):
    logger.debug("davepool_id_to_cells_map.keys():  {}".format(davepool_id_to_cells_map.keys()))

    authoritative_well_list = []
    all_median_data_by_cell = DataByCell(cell_data_map={})
    all_count_data_by_cell = DataByCell(cell_data_map={})

    for dd in davepool_data_objects:
        cells = davepool_id_to_cells_map[dd.davepool_id]
        logger.debug("pools:  {}".format(cells))

        (median_data_by_cell), (count_data_by_cell) = build_data_by_cell(cells, dd)

        if len(authoritative_well_list) == 0:
            authoritative_well_list = median_data_by_cell.well_list
        else:
            assert authoritative_well_list == median_data_by_cell.well_list, (authoritative_well_list,
                                                                              median_data_by_cell.well_list)
            assert authoritative_well_list == count_data_by_cell.well_list, (authoritative_well_list,
                                                                             count_data_by_cell.well_list)

        combine_maps_with_checks(median_data_by_cell.cell_data_map, all_median_data_by_cell.cell_data_map)
        combine_maps_with_checks(count_data_by_cell.cell_data_map, all_count_data_by_cell.cell_data_map)

    all_median_data_by_cell.well_list = authoritative_well_list
    all_count_data_by_cell.well_list = authoritative_well_list

    return (all_median_data_by_cell, all_count_data_by_cell)


def build_gctoo(prism_replicate_name, perturbagen_list, data_by_cell):


    #build column metadata dataframe:
    def column_ID_builder(perturbagen):
        return prism_replicate_name + ":" + perturbagen.well_id

    col_metadata_df = prism_metadata.convert_objects_to_metadata_df(column_ID_builder, perturbagen_list,
                                                                             {"well_id":"pert_well"})
    for col_annot in _remove_col_annotations:
        if col_annot in col_metadata_df.columns:
            col_metadata_df.drop(col_annot, axis=1, inplace=True)

    col_metadata_df.sort_index(inplace=True)
    col_metadata_df['prism_replicate'] = prism_replicate_name
    col_metadata_df['data_level'] = 'assemble'
    col_metadata_df['provenance'] = 'assembled'
    logger.info("my_gctoo.col_metadata_df.shape:  {}".format(col_metadata_df.shape))
    logger.debug("my_gctoo.col_metadata_df:  {}".format(col_metadata_df))
    ########################################

    #build row metadata dataframe:
    def row_ID_builder(prism_cell_obj):
        return prism_cell_obj.id

    row_metadata_df = prism_metadata.convert_objects_to_metadata_df(row_ID_builder,
        data_by_cell.cell_data_map.keys(), {})

    for row_annot in _remove_row_annotations:
        if row_annot in row_metadata_df.columns:
            row_metadata_df.drop(row_annot, axis=1, inplace=True)

    row_metadata_df.sort_index(inplace=True)
    logger.info("my_gctoo.row_metadata_df.shape:  {}".format(row_metadata_df.shape))
    logger.debug("my_gctoo.row_metadata_df:  {}".format(row_metadata_df))
    ########################################

    #build data dataframe - will have the cells as columns and rows as wells, and then transpose
    #start by building mapping between cell ID and corresponding data for that cell, to populate dataframe columns
    cell_id_data_map = {}
    for (c, data) in data_by_cell.cell_data_map.items():
        id = row_ID_builder(c)
        cell_id_data_map[id] = data
    logger.debug("cell_id_data_map:  {}".format(cell_id_data_map))

    #build index for the rows of the dataframe using what is actually the column ID (since it will be transposed)
    well_perturbagen_map = {}
    for p in perturbagen_list:
        well_perturbagen_map[p.well_id] = p
    data_df_column_ids = []
    for w in data_by_cell.well_list:
        p = well_perturbagen_map[w]
        data_df_column_ids.append(column_ID_builder(p))

    data_df = build_gctoo_data_df(cell_id_data_map, data_df_column_ids)
    ########################################

    my_gctoo = GCToo.GCToo(data_df=data_df, row_metadata_df=row_metadata_df, col_metadata_df=col_metadata_df)

    return my_gctoo

def build_gctoo_data_df(cell_id_data_map, data_df_column_ids):
    '''
    build the pandas dataframe that will be used for the data_df part of a gctoo object
    :param cell_id_data_map:
    :param data_df_column_ids:
    :return:
    '''
    data_df = pandas.DataFrame(cell_id_data_map, index=data_df_column_ids).T
    data_df.sort_index(axis=0, inplace=True)
    data_df.sort_index(axis=1, inplace=True)
    data_df.replace("", value=_NaN, inplace=True)
    logger.info("data_df.shape:  {}".format(data_df.shape))
    logger.debug("data_df:  {}".format(data_df))

    return data_df


def main(prism_replicate_name, outfile, all_perturbagens, davepool_data_objects, prism_cell_list):

    # Build one-to-many mapping between davepool ID and the multiple PRISM cell lines that are within that davepool
    davepool_id_to_cells_map = build_davepool_id_to_cells_map(prism_cell_list)

    # Put all the data in gct-able form


    (all_median_data_by_cell, all_count_data_by_cell) = process_data(davepool_data_objects,
                                                                     davepool_id_to_cells_map)

    # Create full outfile, build the gct, and write it out!
    median_outfile = os.path.join(outfile, prism_replicate_name + "_MEDIAN.gct")
    median_gctoo = build_gctoo(prism_replicate_name, all_perturbagens, all_median_data_by_cell)
    write_gctoo.write(median_gctoo, median_outfile, data_null=_NaN, filler_null=_null)

    count_outfile = os.path.join(outfile, prism_replicate_name + "_COUNT.gct")
    count_gctoo = build_gctoo(prism_replicate_name, all_perturbagens, all_count_data_by_cell)
    write_gctoo.write(count_gctoo, count_outfile, data_null=_NaN, filler_null=_null)

    # Validate that all the expected meta-data is present
    validate_prism_gct.check_headers(median_outfile)
    validate_prism_gct.check_headers(count_outfile)