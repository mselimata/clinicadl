def preprocessing_t1w(bids_directory, 
        caps_directory, 
        tsv, 
        ref_template, 
        working_directory=None):

   """
    This preprocessing pipeline includes globally three steps:
    1) N4 bias correction (performed with ANTS).
    2) Linear registration to MNI (MNI icbm152 nlinear sym template)
       (performed with ANTS) - RegistrationSynQuick.
    3) Cropping the background (in order to save computational power).
    4) Histogram-based intensity normalization. This is a custom function
       performed by the binary ImageMath included with ANTS. 

    Parameters
    ----------
    bids_directory: str
       Folder with BIDS structure.
    caps_directory: str
       Folder where CAPS structure will be stored.
    ref_template: str
       reference template used for image registration.
    working_directory: str
       Folder containing a temporary space to save intermediate results.
   """
   
   
   from clinica.utils.inputs import check_bids_folder
   from clinica.utils.participant import get_subject_session_list
   from clinica.utils.exceptions import ClinicaBIDSError, ClinicaException
   from clinica.utils.inputs import clinica_file_reader
   from clinica.utils.input_files import T1W_NII

   check_bids_folder(bids_directory)
   input_dir = bids_directory
   is_bids_dir = True
   base_dir = working_directory

   sessions, subjects = get_subject_session_list(
           input_dir,
           tsv,
           is_bids_dir,
           False,
           base_dir
           )

   from clinica.utils.exceptions import ClinicaBIDSError, ClinicaException
   from clinica.utils.inputs import clinica_file_reader
   from clinica.utils.input_files import T1W_NII
   import nipype.pipeline.engine as npe
   import nipype.interfaces.utility as nutil
   from nipype.interfaces import ants
   from clinica.utils.filemanip import get_subject_id


   # Inputs from anat/ folder
   # ========================
   # T1w file:
   try:
       t1w_files = clinica_file_reader(subjects,
               sessions,
               bids_directory,
               T1W_NII)
   except ClinicaException as e:
       err = 'Clinica faced error(s) while trying to read files in your CAPS directory.\n' + str(e)
       raise ClinicaBIDSError(err)

   def get_input_fields():
       """"Specify the list of possible inputs of this pipelines.
       Returns:
       A list of (string) input fields name.
       """
       return ['t1w']

   read_node = npe.Node(name="ReadingFiles",
           iterables=[
               ('t1w', t1w_files),
               ],
           synchronize=True,
           interface=nutil.IdentityInterface(
               fields=get_input_fields())
           )
   
   image_id_node = npe.Node(
           interface=nutil.Function(
               input_names=['bids_or_caps_file'],
               output_names=['image_id'],
               function= get_subject_id),
           name='ImageID'
           )

   ## The core (processing) nodes

   # 1. N4biascorrection by ANTS. It uses nipype interface.
   n4biascorrection = npe.Node(
           name='n4biascorrection',
           interface=ants.N4BiasFieldCorrection(
               dimension=3, 
               save_bias=True, 
               bspline_fitting_distance=600
               )
           )

   # 2. `RegistrationSynQuick` by *ANTS*. It uses nipype interface.
   ants_registration_node = npe.Node(
           name='antsRegistrationSynQuick',
           interface=ants.RegistrationSynQuick()
           )
   ants_registration_node.inputs.fixed_image = ref_template
   ants_registration_node.inputs.transform_type = 'a'
   ants_registration_node.inputs.dimension = 3

   # 3. Crop image (using nifti). It uses custom interface, from utils file
   from .T1_linear_utils import crop_nifti

   cropnifti = npe.Node(
           name='cropnifti',
           interface=nutil.Function(
               function=crop_nifti,
               input_names=['input_img', 'ref_img'],
               output_names=['output_img', 'crop_template']
               )
           )
   cropnifti.inputs.ref_img = ref_template

   
   #### Deprecrecated ####
   #### This step was not used in the final version ####
   # 4. Histogram-based intensity normalization. This is a custom function
   #    performed by the binary `ImageMath` included with *ANTS*.

#   from .T1_linear_utils import ants_histogram_intensity_normalization
#
#   ## histogram-based intensity normalization
#   intensitynorm = npe.Node(
#           name='intensitynormalization',
#           interface=nutil.Function(
#               input_names=['image_dimension', 'crop_template', 'input_img'],
#               output_names=['output_img'],
#               function=ants_histogram_intensity_normalization
#               )
#           )
#   intensitynorm.inputs.image_dimension = 3

   ## DataSink and the output node

   from .T1_linear_utils import (container_from_filename, get_data_datasink)
   # Create node to write selected files into the CAPS
   from nipype.interfaces.io import DataSink

   get_ids = npe.Node(
           interface=nutil.Function(
               input_names=['image_id'],
               output_names=['image_id_out', 'subst_ls'],
               function=get_data_datasink),
           name="GetIDs")
       
   # Find container path from t1w filename
   # =====================================
   container_path = npe.Node(
           nutil.Function(
               input_names=['bids_or_caps_filename'],
               output_names=['container'],
               function=container_from_filename),
           name='ContainerPath')

   write_node = npe.Node(
               name="WriteCaps",
                   interface=DataSink()
                   )
   write_node.inputs.base_directory = caps_directory
   write_node.inputs.parameterization = False

   ## Connectiong the workflow
   from clinica.utils.nipype import fix_join

   wf = npe.Workflow(name='t1_linear_dl', base_dir=working_directory)

   wf.connect([
       (read_node, image_id_node, [('t1w', 'bids_or_caps_file')]),
       (read_node, container_path, [('t1w', 'bids_or_caps_filename')]),
       (image_id_node , ants_registration_node, [('image_id', 'output_prefix')]),
       (read_node, n4biascorrection, [("t1w", "input_image")]),

       (n4biascorrection, ants_registration_node, [('output_image', 'moving_image')]),

       (ants_registration_node, cropnifti, [('warped_image', 'input_img')]),

       # Connect to DataSink
       (container_path, write_node, [(('container', fix_join, 't1_linear'), 'container')]),
       (image_id_node, get_ids, [('image_id', 'image_id')]),
       (get_ids, write_node, [('image_id_out', '@image_id')]),
       (get_ids, write_node, [('subst_ls', 'substitutions')]),
       #(get_ids, write_node, [('regexp_subst_ls', 'regexp_substitutions')]),
       (n4biascorrection, write_node, [('output_image', '@outfile_corr')]),
       (ants_registration_node, write_node, [('warped_image', '@outfile_reg')]),
       (cropnifti, write_node, [('output_img', '@outfile_crop')]),
       ])

   return wf