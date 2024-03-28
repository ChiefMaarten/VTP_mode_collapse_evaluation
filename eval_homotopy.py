import numpy as np
import argparse
import os
import sys
import subprocess
import shutil
sys.path.append(os.getcwd())
from data.dataloader_debug import data_generator
from utils.torch import *
from utils.config import Config
from model.model_lib import model_dict
from utils.utils import prepare_seed, print_log, mkdir_if_missing
# from eval_utils import *
from utils.homotopy import *
import plotly.graph_objects as go
import plotly.express as px
from agent_class import Agent

""" setup """
cfg = Config('nuscenes_5sample_agentformer' )
epochs = [cfg.get_last_epoch()]
epoch = epochs[0]


torch.set_default_dtype(torch.float32)
device = torch.device('cuda', index=0) if 0 >= 0 and torch.cuda.is_available() else torch.device('cpu')
if torch.cuda.is_available(): torch.cuda.set_device(0)
torch.set_grad_enabled(False)
log = open(os.path.join(cfg.log_dir, 'log_test.txt'), 'w')


model_id = cfg.get('model_id', 'agentformer')
model = model_dict[model_id](cfg)
model.set_device(device)
model.eval()
cp_path = cfg.model_path % epoch
print_log(f'loading model from checkpoint: {cp_path}', log, display=True)
model_cp = torch.load(cp_path, map_location='cpu')
model.load_state_dict(model_cp['model_dict'], strict=False)

""""  #################  """


def get_model_prediction(data, sample_k):
    model.set_data(data)
    recon_motion_3D, _ = model.inference(mode='recon', sample_num=sample_k)
    sample_motion_3D, data = model.inference(mode='infer', sample_num=sample_k, need_weights=False)
    sample_motion_3D = sample_motion_3D.transpose(0, 1).contiguous()
    return recon_motion_3D, sample_motion_3D




""" Get predictions and compute metrics """

split = 'val'
plot = False
use_crossing_pairs = False


generator = data_generator(cfg, log, split=split, phase='testing')
scene_preprocessors = generator.sequence

for scene in scene_preprocessors:

    gt = scene.gt
    pred_frames = scene.pred_frames
    df_scene = Agent.process_data(gt)

    # find intersecting agent trajectory pairs
    if use_crossing_pairs:
        raise NotImplementedError
    else:
        pass

    # init agent modification classes here; init interpolation functions, and allow for accel/decel rollouts
    agent_dict = {}
    for agent in df_scene.agent_id.unique():
        df_agent = df_scene[df_scene.agent_id == agent]
        agent_class = Agent(df_agent)
        agent_dict.update({agent: agent_class})


    for frame in pred_frames:
        # frame corresponds to the current timestep, i.e. the last of pre_motion
        data = scene(frame)
        if data is None:
            print('Frame skipped in loop')
            continue

        seq_name, frame = data['seq'], data['frame']
        frame = int(frame)
        sys.stdout.write('testing seq: %s, frame: %06d                \r' % (seq_name, frame))  
        sys.stdout.flush()

        gt_motion_3D = torch.stack(data['fut_motion_3D'], dim=0).to(device) * cfg.traj_scale
        with torch.no_grad():
            recon_motion_3D, sample_motion_3D = get_model_prediction(data, cfg.sample_k)
        recon_motion_3D, sample_motion_3D = recon_motion_3D * cfg.traj_scale, sample_motion_3D * cfg.traj_scale

        # calculate roll-outs
        fut_mod_decel_list = []
        fut_mod_accel_list = []
        for agent_id in data['valid_id']:
            agent = agent_dict[str(int(agent_id))]
            fut_rollout_decel = agent.rollout_future(frame_curr = frame, direction = 'decel')
            fut_rollout_accel = agent.rollout_future(frame_curr = frame, direction = 'accel')
            fut_mod_decel_list.append(fut_rollout_decel)
            fut_mod_accel_list.append(fut_rollout_accel)
        
        fut_mod_decel = torch.from_numpy(np.stack(fut_mod_decel_list)).unsqueeze(0)
        fut_mod_accel = torch.from_numpy(np.stack(fut_mod_accel_list)).unsqueeze(0)

        # calculate homotopy_classes: gt, pred, roll-outs
        fut_motion = np.stack(data['fut_motion_3D']) * data['traj_scale']
        fut_motion_batch = torch.from_numpy(fut_motion).unsqueeze(0)
        angle_diff_gt, homotopy_gt = identify_pairwise_homotopy(fut_motion_batch)
        angle_diff_pred, homotopy_pred = identify_pairwise_homotopy(sample_motion_3D)

        
        pred_frame_agents = data['valid_id']

        if plot:
            data['scene_map'].visualize_trajs(data, sample_motion_3D)
            # also plot roll outs here
            data['scene_map'].visualize_trajs(data, fut_mod_decel)
            data['scene_map'].visualize_trajs(data, fut_mod_accel)   


