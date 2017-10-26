import sys
sys.path.append('/Users/elemire/Workspace/l1ktools')
import broadinstitute_cmap.io.GCToo.parse as parse
import broadinstitute_cmap.io.GCToo.write_gctoo as write_gctoo
from broadinstitute_cmap.io.pandasGEXpress import GCToo
import numpy as np

invariant_rids = ['661', '662', '663', '664', '665', '666', '667', '668', '669', '670']

def normalize(mfi_gctoo, log=True, inv=True):

    # Level 2-3 Normalization based on prism invariant

    #mfi_gctoo = remove_low_bead_wells(mfi_gctoo, count_gctoo)

    mfi_gctoo = remove_outlier_invariants(mfi_gctoo)

    mfi_gctoo.data_df[mfi_gctoo.data_df < 1] = 1

    if log is True:
        data_df = np.log2(mfi_gctoo.data_df)
        mfi_gctoo.col_metadata_df['provenance'] = 'assembled | log2 | median normalized'

    else:
        data_df = mfi_gctoo.data_df
        mfi_gctoo.col_metadata_df['provenance'] = 'assembled | median normalized'

    data_df.round(2)

    if inv is True:
        for column in data_df:
            median = data_df[column][invariant_rids].median()

            for index in data_df[column].index:
                if index not in invariant_rids:
                    data_df[column][index] = data_df[column][index] / median


    mfi_gctoo.col_metadata_df['data_level'] = 'normalized'

    data_df = data_df.loc[~data_df.index.isin(invariant_rids)]
    row_metadata_df = mfi_gctoo.row_metadata_df.loc[~mfi_gctoo.row_metadata_df.index.isin(invariant_rids)]

    new_gctoo = GCToo.GCToo(data_df=data_df, row_metadata_df=row_metadata_df, col_metadata_df=mfi_gctoo.col_metadata_df)

    return new_gctoo

    #if outfile is None:
    #    outfile = filepath[:-10] + 'NORM.gct'
    #else:
    #    outfile = outfile + '_NORM.gct'

    #write_gctoo.write(new_gctoo, outfile)


def remove_low_bead_wells(mfi_gct, count_gct):

    medians = count_gct.data_df.median(axis=0)

    bad_wells = medians[medians < 20].index

    bad_wells = [x for x in bad_wells if x in mfi_gct.data_df.columns]

    data = mfi_gct.data_df.drop(bad_wells, axis=1)
    col_data = mfi_gct.col_metadata_df.drop(bad_wells, axis=0)

    new_gctoo = GCToo.GCToo(data_df=data, col_metadata_df=col_data, row_metadata_df=mfi_gct.row_metadata_df)

    return new_gctoo


def remove_outlier_invariants(gctoo):

    invdata = gctoo.data_df.loc[invariant_rids]

    dmso_inv = invdata.loc[:, gctoo.col_metadata_df.loc[gctoo.col_metadata_df['pert_type'] == 'ctl_vehicle'].index.tolist()]

    #bad_wells = invdata.median()[invdata.median() < dmso_inv.median().quantile(0.005)].index

    bad_wells = invdata.median()[invdata.median() < 600].index

    data = gctoo.data_df.drop(bad_wells, axis=1)
    col_data = gctoo.col_metadata_df.drop(bad_wells, axis=0)

    new_gctoo = GCToo.GCToo(data_df=data, col_metadata_df=col_data, row_metadata_df=gctoo.row_metadata_df)

    return new_gctoo


def dp_normalize(filepath, outfile):

    # For use with DP11/12 protocol (deprecated)

    df = parse.parse(filepath)
    dp11_invariant_rids = ['661', '662', '663', '664', '665', '666', '667', '668', '669', '670']
    dp12_invariant_rids = ['671', '672', '673', '674', '675', '676', '677', '678', '679', '680']

    dp11_dex = df.row_metadata_df[df.row_metadata_df['davepool_id'] == 'DP7'].index.tolist()
    dp12_dex = df.row_metadata_df[df.row_metadata_df['davepool_id'] == 'DP8.1'].index.tolist()

    dp11_df = df.data_df.loc[dp11_dex]

    for column in dp11_df:
        median = dp11_df[column][dp11_invariant_rids].median()

        for index in dp11_df[column].index:
            if index not in dp11_invariant_rids:
                dp11_df[column][index] = dp11_df[column][index] / median

    dp12_df = df.data_df.loc[dp12_dex]

    for column in dp12_df:
        median = dp12_df[column][dp12_invariant_rids].median()

        for index in dp12_df[column].index:
            if index not in dp12_invariant_rids:
                dp12_df[column][index] = dp12_df[column][index] / median

    recombine = dp11_df.append(dp12_df)
    recombine.sort_index(inplace=True)
    df.row_metadata_df.sort_index(inplace=True)
    df.col_metadata_df['provenance'] = 'assembled | median normalized'
    df.col_metadata_df['data_level'] = 'normalized'

    my_gctoo = GCToo.GCToo(data_df=recombine, row_metadata_df=df.row_metadata_df, col_metadata_df=df.col_metadata_df)

    write_gctoo.write(my_gctoo, outfile)