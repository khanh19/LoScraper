import shutil,subprocess,tempfile,unittest
from pathlib import Path
from trending.media import sample_frames
@unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'),'ffmpeg required')
class FrameTests(unittest.TestCase):
 def test_real_decoder_includes_last_frame(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'clip.mp4'
   subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','testsrc=size=96x96:rate=10','-t','2','-pix_fmt','yuv420p',str(path)],check=True)
   frames=sample_frames(path,d)
   self.assertLessEqual(len(frames),12);self.assertGreater(len(frames),1);self.assertEqual(0,frames[0]['time_seconds']);self.assertAlmostEqual(1.9,frames[-1]['time_seconds']);self.assertEqual(19,frames[-1]['frame_index'])
