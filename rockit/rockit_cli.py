import argparse
import logging
import os
import glob
from tomopy import find_center_pc, circ_mask, normalize, minus_log
import tomopy.recon as reconstruction
from tomopy.prep.alignment import find_slits_corners_aps_1id, remove_slits_aps_1id
from tomopy.misc.corr import remove_outlier
from tomopy.prep.normalize import normalize_bg
from tomopy.prep.stripe import remove_all_stripe

import numpy as np
import bm3d_streak_removal as bm3d_rmv
from imars3dv2.filters import tilt
from utilites import get_ind_list, find_proj180_ind, read_tiff_stack, read_tiff_from_full_name_list, set_roi

import warnings
warnings.filterwarnings('ignore')

from samffr.retrieve_matching_ob_dc import RetrieveMatchingOBDC


#LOG_FILE_NAME = "/HFIR/CG1D/shared/autoreduce/rockit.log"
LOG_FILE_NAME = "/Users/j35/Desktop/rockit.log"

# TOP_FOLDER = "/HFIR/CG1D"
TOP_FOLDER = "/Users/j35/IPTS/HFIR/CG1D"


def rockit_cli(args):

	# parsing arguments
	ipts_number = args.ipts_number
	input_folder = args.input_folder
	roi_xmin = args.roi_xmin if args.roi_xmin else 250
	roi_ymin = args.roi_ymin if args.roi_ymin else 600
	roi_xmax = args.roi_xmax if args.roi_xmax else 1250
	roi_ymax = args.roi_ymax if args.roi_ymax else 1300
	roi = [roi_xmin, roi_ymin, roi_xmax, roi_ymax]

	logging.basicConfig(filename=LOG_FILE_NAME,
						filemode='a',
						format='[%(levelname)s] - %(asctime)s - %(message)s',
						level=logging.INFO)
	logger = logging.getLogger("rockit")
	logger.info("*** Starting a new auto-reconstruction ***")
	logger.info(f"IPTS: {ipts_number}")
	logger.info(f"input_folder: {input_folder}")
	logger.info(f"roi_xmin: {roi_xmin}")
	logger.info(f"roi_ymin: {roi_ymin}")
	logger.info(f"roi_xmax: {roi_xmax}")
	logger.info(f"roi_ymax: {roi_ymax}")

	# checking that input folder exists
	if not os.path.exists(input_folder):
		logger.info(f"ERROR: input folder does not exists!")
		logger.info(f"Exiting rockit!")
		exit(0)

	logger.info(f"Checking if input folder exists .... True!")

	# using input folder name, locate the ob and df that match it
	list_sample_data = glob.glob(os.path.join(input_folder, "*.tif*"))
	nbr_tiff_files = len(list_sample_data)
	logger.info(f"Found {nbr_tiff_files} tiff files in input folder.")

	if nbr_tiff_files == 0:
		logger.info(f"Input folder is empty. Leaving rockit now!")
		exit(0)

	print("looking for matching ob and dc")
	logger.info(f"Looking for matching OB and DC!")
	ipts_folder = os.path.join(TOP_FOLDER, f"IPTS-{ipts_number}/raw/")
	logger.info(f"- ipts_folder: {ipts_folder}")
	o_main = RetrieveMatchingOBDC(list_sample_data=list_sample_data,
								  IPTS_folder=ipts_folder)
	o_main.run()

	list_ob = o_main.get_matching_ob()
	list_dc = o_main.get_matching_dc()

	logger.info(f"- found {len(list_ob)} matching OB!")
	logger.info(f"- found {len(list_dc)} matching DC!")

	# build script to run yuxuan's code

	# projections
	print("loading projections")
	ct_name, ang_deg, theta, ind_list = get_ind_list(os.listdir(input_folder))
	proj180_ind = find_proj180_ind(ang_deg)[0]
	logger.info(f"- Found index of 180 degree projections: {proj180_ind}")
	logger.info(f"Loading projections ....")
	proj = read_tiff_stack(fdir=input_folder, fname=ct_name)
	logger.info(f"Loading CT projections .... Done!")

	# ob
	print("loading ob")
	logger.info(f"Loading OB ....")
	ob = read_tiff_from_full_name_list(list_ob)
	logger.info(f"Loading OB .... Done!")

	# dc
	print("loading dc")
	logger.info(f"Loading DC ...")
	dc = read_tiff_from_full_name_list(list_dc)
	logger.info(f"Loading DC ... Done!")

	# detect and crop the slits
	print("detecting and cropping the slits")
	logger.info(f"Detecting and cropping the slits ....")
	slit_box_corners = find_slits_corners_aps_1id(img=ob[0], method='simple')
	proj = remove_slits_aps_1id(proj, slit_box_corners)
	ob = remove_slits_aps_1id(ob, slit_box_corners)
	dc = remove_slits_aps_1id(dc, slit_box_corners)
	logger.info(f"Detecting and cropping the slits .... Done!")

	# Define the ROI
	print("removing slits aperture")
	logger.info(f"removing slits aperture ...")
	roi_corners = set_roi(corners=slit_box_corners, xmin=roi[0], ymin=roi[1], xmax=roi[2], ymax=roi[3])
	logger.info(f"- corners detected are {roi_corners}")
	proj_crop = remove_slits_aps_1id(proj, roi_corners)
	ob_crop = remove_slits_aps_1id(ob, roi_corners)
	dc_crop = remove_slits_aps_1id(dc, roi_corners)
	logger.info(f"removing slits aperture ... Done!")

	# Remove outliers
	print("remove outliers")
	logger.info(f"removing outliers ...")
	logger.info(f"- parameter used: 50")
	proj_crop = remove_outlier(proj_crop, 50)
	logger.info(f"removing outliers ... Done!")

	# Normalization
	print("normalization")
	logger.info(f"Normalization ...")
	proj_norm = normalize(proj_crop, ob_crop, dc_crop)
	logger.info(f"Normalization ... Done!")

	# beam fluctuation correction
	print(f"beam fluctuation")
	logger.info(f"Beam fluctuation ....")
	logger.info(f"- air: 50")
	proj_norm = normalize_bg(proj_norm, air=50)
	logger.info(f"Beam fluctuation .... Done!")

	# minus log conversion
	print("minus log conversion")
	logger.info(f"minus log conversion ...")
	proj_mlog = minus_log(proj_norm)
	logger.info(f"minus log conversion ... Done!")

	# ring artifact removal
	print("ring artifact removal")
	logger.info(f"ring artifact removal")
	proj_rmv = remove_all_stripe(proj_mlog)
	logger.info(f"ring artifact removal ... Done!")

	# find and correct tilt
	print(f"find and correct tilt")
	logger.info(f"find and correct tilt")
	tilt_ang = tilt.calculate_tilt(image0=proj_rmv[0], image180=proj_rmv[proj180_ind])
	logger.info(f"- tilt angle: {tilt_ang.x}")
	proj_tilt = tilt.apply_tilt_correction(proj_rmv, tilt_ang.x)
	logger.info(f"find and correct tilt ... Done!")

	# find center of rotation
	print(f"center of rotation")
	logger.info(f"center of rotation")
	rot_center = find_center_pc(np.squeeze(proj_tilt[0, :, :]),
					     		  np.squeeze(proj_tilt[proj180_ind, :, :]), tol=0.5)
	logger.info(f"center of rotation ... Done!")

	# reconstruction
	print(f"reconstruction")
	logger.info(f"reconstruction")
	recon = reconstruction(proj_tilt, theta, center=rot_center, algorithm='gridrec', sinogram_order=False)
	recon = circ_mask(recon, axis=0, ratio=0.95)
	logger.info(f"reconstruction ... done")


if __name__ == "__main__":
	# import numpy as np
	# import bm3d_streak_removal as bm3d_rmv
	# from imars3dv2.filters import tilt
	# from utilites import get_ind_list, find_proj180_ind, read_tiff_stack, read_tiff_from_full_name_list, set_roi
	#
	# import warnings
	#
	# warnings.filterwarnings('ignore')
	#
	# from samffr.retrieve_matching_ob_dc import RetrieveMatchingOBDC
	#
	# # LOG_FILE_NAME = "/HFIR/CG1D/shared/autoreduce/rockit.log"
	# LOG_FILE_NAME = "/Users/j35/Desktop/rockit.log"
	#
	# # TOP_FOLDER = "/HFIR/CG1D"
	# TOP_FOLDER = "/Users/j35/IPTS/HFIR/CG1D"

	parser = argparse.ArgumentParser(description="""
	Reconstruct a set of projections from a given folder,

	example:
		python rockit/rockit_cli 27158 input_folder_name -roi_xmin 250 -roi_ymin 600 -roi_xmax 1250 -roi_ymax 1300
	""",
									 formatter_class=argparse.RawDescriptionHelpFormatter,
									 epilog="NB: the input folder name is mandatory")

	parser.add_argument('ipts_number',
						help='IPTS of current experiment')
	parser.add_argument('input_folder',
						help='folder containing the projections')
	parser.add_argument('-roi_xmin',
						type=int,
						help='xmin ROI to crop')
	parser.add_argument('-roi_ymin',
						type=int,
						help='ymin ROI to crop')
	parser.add_argument('-roi_xmax',
						type=int,
						help='xmax ROI to crop')
	parser.add_argument('-roi_ymax',
						type=int,
						help='ymax ROI to crop')

	args = parser.parse_args()

	rockit_cli(args)
