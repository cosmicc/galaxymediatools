#!/usr/bin/python

import ConfigParser
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

# Config stuff.
config_file_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'PlexComskip.conf')
if not os.path.exists(config_file_path):
  print 'Config file not found: %s' % config_file_path
  print 'Make a copy of PlexConfig.conf.example named PlexConfig.conf, modify as necessary, and place in the same directory as this script.'
  sys.exit(1)

config = ConfigParser.SafeConfigParser({'comskip-ini-path' : os.path.join(os.path.dirname(os.path.realpath(__file__)), 'comskip.ini'), 'temp-root' : tempfile.gettempdir()})
config.read(config_file_path)

COMSKIP_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'comskip-path')))
COMSKIP_INI_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'comskip-ini-path')))
FFMPEG_PATH = os.path.expandvars(os.path.expanduser(config.get('Helper Apps', 'ffmpeg-path')))
LOG_FILE_PATH = os.path.expandvars(os.path.expanduser(config.get('Logging', 'logfile-path')))
CONSOLE_LOGGING = config.getboolean('Logging', 'console-logging')
TEMP_ROOT = os.path.expandvars(os.path.expanduser(config.get('File Manipulation', 'temp-root')))
# added temp_root_b to store compressed temp mkv
TEMP_ROOT_b = os.path.expandvars(os.path.expanduser(config.get('File Manipulation', 'temp-root_b')))
#
COPY_ORIGINAL = config.getboolean('File Manipulation', 'copy-original')
SAVE_ALWAYS = config.getboolean('File Manipulation', 'save-always')
SAVE_FORENSICS = config.getboolean('File Manipulation', 'save-forensics')

# Logging.
session_uuid = str(uuid.uuid4())
fmt = '%%(asctime)-15s [%s] %%(message)s' % session_uuid[:6]
if not os.path.exists(os.path.dirname(LOG_FILE_PATH)):
  os.makedirs(os.path.dirname(LOG_FILE_PATH))
logging.basicConfig(level=logging.INFO, format=fmt, filename=LOG_FILE_PATH)
if CONSOLE_LOGGING:
  console = logging.StreamHandler()
  console.setLevel(logging.INFO)
  formatter = logging.Formatter('%(message)s')
  console.setFormatter(formatter)
  logging.getLogger('').addHandler(console)

# Human-readable bytes.
def sizeof_fmt(num, suffix='B'):

  for unit in ['','K','M','G','T','P','E','Z']:
    if abs(num) < 1024.0:
      return "%3.1f%s%s" % (num, unit, suffix)
    num /= 1024.0
  return "%.1f%s%s" % (num, 'Y', suffix)

if len(sys.argv) < 2:
  print 'Usage: PlexComskip.py input-file.mkv'
  sys.exit(1)

# Clean up after ourselves and exit.
def cleanup_and_exit(temp_dir, keep_temp=False):
  if keep_temp:
    logging.info('Leaving temp files in: %s' % temp_dir)
  else:
    try:
      os.chdir(os.path.expanduser('~'))  # Get out of the temp dir before we nuke it (causes issues on NTFS)
      shutil.rmtree(temp_dir)
    except Exception, e:
      logging.error('Problem whacking temp dir: %s' % temp_dir)
      logging.error(str(e))

  # Exit cleanly.
  logging.info('Done processing!')
  sys.exit
  
# Clean up after ourselves and exit.
def cleanup_and_exit(temp_dir_b, keep_temp=False):
  if keep_temp:
    logging.info('Leaving temp files in: %s' % temp_dir_b)
  else:
    try:
      os.chdir(os.path.expanduser('~'))  # Get out of the temp dir before we nuke it (causes issues on NTFS)
      shutil.rmtree(temp_dir_b)
    except Exception, e:
      logging.error('Problem whacking temp dir: %s' % temp_dir_b)
      logging.error(str(e))

  # Exit cleanly.
  logging.info('Done processing!')
  sys.exit(0)

# If we're in a git repo, let's see if we can report our sha.
logging.info('PlexComskip got invoked from %s' % os.path.realpath(__file__))
try:
  git_sha = subprocess.check_output('git rev-parse --short HEAD', shell=True)
  if git_sha:
    logging.info('Using version: %s' % git_sha.strip())
except: pass

# On to the actual work.
try:
  video_path = sys.argv[1]
  temp_dir_b = os.path.join(TEMP_ROOT_b, session_uuid)
  os.makedirs(temp_dir_b)
  # os.chdir(temp_dir_b)
  temp_dir = os.path.join(TEMP_ROOT, session_uuid)
  os.makedirs(temp_dir)
  os.chdir(temp_dir)
  
  logging.info('Using session ID: %s' % session_uuid)
  logging.info('Using temp dir: %s' % temp_dir)
  logging.info('Using input file: %s' % video_path)


  original_video_dir = os.path.dirname(video_path)
  video_basename = os.path.basename(video_path)
  video_name, video_ext = os.path.splitext(video_basename)

except Exception, e:
  logging.error('Something went wrong setting up temp paths and working files: %s' % e)
  sys.exit(0)

try:
  if COPY_ORIGINAL or SAVE_ALWAYS: 
    temp_video_path = os.path.join(temp_dir, video_basename)
    logging.info('Copying file to work on it: %s' % temp_video_path)
    shutil.copy(video_path, temp_dir)
  else:
    temp_video_path = video_path

  # Process with comskip.
  cmd = [COMSKIP_PATH, '--output', temp_dir, '--ini', COMSKIP_INI_PATH, temp_video_path]
  logging.info('[comskip] Command: %s' % cmd)
  subprocess.call(cmd)

except Exception, e:
  logging.error('Something went wrong during comskip analysis: %s' % e)
  cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)
  cleanup_and_exit(temp_dir_b, SAVE_ALWAYS or SAVE_FORENSICS)

edl_file = os.path.join(temp_dir, video_name + '.edl')
logging.info('Using EDL: ' + edl_file)
try:
  segments = []
  prev_segment_end = 0.0
  if os.path.exists(edl_file):
    with open(edl_file, 'rb') as edl:
      
      # EDL contains segments we need to drop, so chain those together into segments to keep.
      for segment in edl:
        start, end, something = segment.split()
        if float(start) == 0.0:
          logging.info('Start of file is junk, skipping this segment...')
        else:
          keep_segment = [float(prev_segment_end), float(start)]
          logging.info('Keeping segment from %s to %s...' % (keep_segment[0], keep_segment[1]))
          segments.append(keep_segment)
        prev_segment_end = end

  # Write the final keep segment from the end of the last commercial break to the end of the file.
  keep_segment = [float(prev_segment_end), -1]
  logging.info('Keeping segment from %s to the end of the file...' % prev_segment_end)
  segments.append(keep_segment)

  segment_files = []
  segment_list_file_path = os.path.join(temp_dir, 'segments.txt')
  with open(segment_list_file_path, 'wb') as segment_list_file:
    for i, segment in enumerate(segments):
      segment_name = 'segment-%s' % i
      segment_file_name = '%s%s' % (segment_name, video_ext)
      if segment[1] == -1:
        duration_args = []
      else:
        duration_args = ['-t', str(segment[1] - segment[0])]
      cmd = [FFMPEG_PATH, '-i', temp_video_path, '-ss', str(segment[0])]
      cmd.extend(duration_args)
      cmd.extend(['-c', 'copy', segment_file_name])
      logging.info('[ffmpeg] Command: %s' % cmd)
      try:
        subprocess.call(cmd)
      except Exception, e:
        logging.error('Exception running ffmpeg: %s' % e)
        cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)
      
      # If the last drop segment ended at the end of the file, we will have written a zero-duration file.
      if os.path.exists(segment_file_name):
        if os.path.getsize(segment_file_name) < 1000:
          logging.info('Last segment ran to the end of the file, not adding bogus segment %s for concatenation.' % (i + 1))
          continue

        segment_files.append(segment_file_name)
        segment_list_file.write('file %s\n' % segment_file_name)

except Exception, e:
  logging.error('Something went wrong during splitting: %s' % e)
  cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)

logging.info('Going to concatenate %s files from the segment list.' % len(segment_files))
try:
  cmd = [FFMPEG_PATH, '-y', '-f', 'concat', '-i', segment_list_file_path, '-c', 'copy', os.path.join(temp_dir, video_basename)]
  logging.info('[ffmpeg] Command: %s' % cmd)
  subprocess.call(cmd)

except Exception, e:
  logging.error('Something went wrong during concatenation: %s' % e)
  cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)

logging.info('Sanity checking our work...')
try:
  input_size = os.path.getsize(video_path)
  output_size = os.path.getsize(os.path.join(temp_dir, video_basename))
  if input_size and 1.01 > float(output_size) / float(input_size) > 0.99:
    logging.info('Output file size was too similar (doesn\'t look like we did much); we won\'t replace the original: %s -> %s' % (sizeof_fmt(input_size), sizeof_fmt(output_size)))
    cleanup_and_exit(temp_dir, SAVE_ALWAYS)
  elif input_size and 1.1 > float(output_size) / float(input_size) > 0.5:
    #
    #  attempting to add x264 compression to the stripped commercial file before overiding the origional
    #  ffmpeg -i inputfile.mkv -crf 18 -map 0 -acodec copy -scodec copy -c:v libx264 -threads 0 -preset veryslow outputfile.mkv
    #
    cmd = [FFMPEG_PATH, '-i', os.path.join(temp_dir, video_basename), '-vf', 'yadif=0:-1:1', '-crf', '20', '-map', '0', '-acodec', 'copy', '-scodec', 'copy', '-c:v', 'libx264', '-threads', '0', '-preset', 'medium', os.path.join(temp_dir_b, video_basename)]
    subprocess.call(cmd)
    #
    #
    #
    logging.info('Output file size looked sane, we\'ll replace the original: %s -> %s' % (sizeof_fmt(input_size), sizeof_fmt(output_size)))
    logging.info('Copying the output file into place: %s -> %s' % (video_basename, original_video_dir))
    
    shutil.copy(os.path.join(temp_dir_b, video_basename), original_video_dir)
    # shutil.copy(os.path.join(temp_dir, video_basename), original_video_dir)
    cleanup_and_exit(temp_dir, SAVE_ALWAYS)
    cleanup_and_exit(temp_dir_b, SAVE_ALWAYS)
  else:
    logging.info('Output file size looked wonky (too big or too small); we won\'t replace the original: %s -> %s' % (sizeof_fmt(input_size), sizeof_fmt(output_size)))
    cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)
    cleanup_and_exit(temp_dir_b, SAVE_ALWAYS or SAVE_FORENSICS)
except Exception, e:
  logging.error('Something went wrong during sanity check: %s' % e)
  cleanup_and_exit(temp_dir, SAVE_ALWAYS or SAVE_FORENSICS)
  cleanup_and_exit(temp_dir_b, SAVE_ALWAYS or SAVE_FORENSICS)

