from sandbox.rocky.tf.algos.maml_il import MAMLIL

from rllab.baselines.linear_feature_baseline import LinearFeatureBaseline
from rllab.baselines.gaussian_mlp_baseline import GaussianMLPBaseline
from rllab.baselines.maml_gaussian_mlp_baseline import MAMLGaussianMLPBaseline
from rllab.baselines.zero_baseline import ZeroBaseline
from rllab.envs.normalized_env import normalize
from rllab.misc.instrument import stub, run_experiment_lite
from sandbox.rocky.tf.policies.maml_minimal_gauss_mlp_policy import MAMLGaussianMLPPolicy as basic_policy
#from sandbox.rocky.tf.policies.maml_minimal_gauss_mlp_policy_adaptivestep import MAMLGaussianMLPPolicy as fullAda_basic_policy
from sandbox.rocky.tf.policies.maml_minimal_gauss_mlp_policy_adaptivestep_biastransform import MAMLGaussianMLPPolicy as fullAda_Bias_policy
from sandbox.rocky.tf.policies.maml_minimal_gauss_mlp_policy_biasonlyadaptivestep_biastransform import MAMLGaussianMLPPolicy as biasAda_Bias_policy
from sandbox.rocky.tf.policies.maml_minimal_conv_gauss_mlp_policy import MAMLGaussianMLPPolicy as conv_policy


from sandbox.rocky.tf.optimizers.quad_dist_expert_optimizer import QuadDistExpertOptimizer
from sandbox.rocky.tf.optimizers.first_order_optimizer import FirstOrderOptimizer
from sandbox.rocky.tf.envs.base import TfEnv
import sandbox.rocky.tf.core.layers as L

from rllab.envs.mujoco.ant_env_rand_goal_ring import AntEnvRandGoalRing
from multiworld.envs.mujoco.sawyer_xyz.push.sawyer_push import  SawyerPushEnv 
from multiworld.envs.mujoco.sawyer_xyz.pickPlace.sawyer_pick_and_place import SawyerPickPlaceEnv
from multiworld.envs.mujoco.sawyer_xyz.door.sawyer_door_open import  SawyerDoorOpenEnv
from multiworld.core.flat_goal_env import FlatGoalEnv
from multiworld.core.finn_maml_env import FinnMamlEnv
from multiworld.core.wrapper_env import NormalizedBoxEnv

import tensorflow as tf
import time
from rllab.envs.gym_env import GymEnv

from maml_examples.maml_experiment_vars import MOD_FUNC
import numpy as np
import random as rd
import pickle

import rllab.misc.logger as logger
from rllab.misc.ext import  set_seed
import os

def setup(seed , n_parallel, log_dir ):

    if seed is not None:
        set_seed(seed)

    if n_parallel > 0:
        from rllab.sampler import parallel_sampler
        parallel_sampler.initialize(n_parallel=n_parallel)
        if seed is not None:
            parallel_sampler.set_seed(seed)
    
    if os.path.isdir(log_dir)==False:
        os.makedirs(log_dir , exist_ok = True)

    logger.set_snapshot_dir(log_dir)
    logger.add_tabular_output(log_dir+'/progress.csv')



expl = False 
l2loss_std_mult = 0 ; use_corr_term = False
extra_input =None ; extra_input_dim = 0

beta_steps = 1 ;
meta_step_size = 0.01 ; num_grad_updates = 1
pre_std_modifier = 1.0 ; post_std_modifier = 0.00001 
limit_demos_num = None 

test_on_training_goals = True


def experiment(variant):

    seed = variant['seed'] ; n_parallel = 1; log_dir = variant['log_dir']

    setup(seed, n_parallel , log_dir)

    fast_batch_size = variant['fbs']  ; meta_batch_size = variant['mbs']
    adam_steps = variant['adam_steps'] ; max_path_length = variant['max_path_length']

    dagger = variant['dagger'] ; expert_policy_loc = variant['expert_policy_loc']

    ldim = variant['ldim'] ; init_flr =  variant['init_flr'] ; policyType = variant['policyType'] ; use_maesn = variant['use_maesn']
    EXPERT_TRAJ_LOCATION = variant['expertDataLoc']
    envType = variant['envType']

    tasksFile = path_to_multiworld + 'multiworld/envs/goals/' + variant['tasksFile']+'.pkl'

    all_tasks = pickle.load(open(tasksFile, 'rb'))
    assert meta_batch_size<=len(all_tasks)
    tasks = all_tasks[:meta_batch_size]

    use_images = 'conv' in policyType


    if 'Push' == envType:       
        baseEnv = SawyerPushEnv(tasks = tasks , image = use_images , mpl = max_path_length)

    elif envType == 'sparsePush':
        baseEnv = SawyerPushEnv(tasks = tasks , image = use_images , mpl = max_path_length  , rewMode = 'l2Sparse')


    elif 'PickPlace' in envType:
        baseEnv = SawyerPickPlaceEnv( tasks = tasks , image = use_images , mpl = max_path_length)

    elif 'Door' in envType:
        baseEnv = SawyerDoorOpenEnv(tasks = tasks , image = use_images , mpl = max_path_length) 
        
    elif 'Ant' in envType:
        env = TfEnv(normalize(AntEnvRandGoalRing()))

    elif 'claw' in envType:
        env = TfEnv(DClawScrewRandGoal())

    else:
        assert True == False

    if envType in ['Push' , 'PickPlace' , 'Door']:
        if use_images:
            obs_keys = ['img_observation']
        else:
            obs_keys = ['state_observation']
        env = TfEnv(NormalizedBoxEnv( FinnMamlEnv(FlatGoalEnv(baseEnv, obs_keys=obs_keys) , reset_mode = 'idx')))

    
    algoClass = MAMLIL
    baseline = LinearFeatureBaseline(env_spec = env.spec)

    load_policy = variant['load_policy']
    
    if load_policy !=None:
        policy = None
        load_policy = variant['load_policy']
        # if 'conv' in load_policy:
        #     baseline = ZeroBaseline(env_spec=env.spec)

    elif 'fullAda_Bias' in policyType:
       
        policy = fullAda_Bias_policy(
                name="policy",
                env_spec=env.spec,
                grad_step_size=init_flr,
                hidden_nonlinearity=tf.nn.relu,
                hidden_sizes=(100,100),
                init_flr_full=init_flr,
                latent_dim=ldim
            )

    elif 'biasAda_Bias' in policyType:

        policy = biasAda_Bias_policy(
                name="policy",
                env_spec=env.spec,
                grad_step_size=init_flr,
                hidden_nonlinearity=tf.nn.relu,
                hidden_sizes=(100,100),
                init_flr_full=init_flr,
                latent_dim=ldim
            )

    elif 'basic' in policyType:
        policy =  basic_policy(
        name="policy",
        env_spec=env.spec,
        grad_step_size=init_flr,
        hidden_nonlinearity=tf.nn.relu,
        hidden_sizes=(100, 100),                  
        extra_input_dim=(0 if extra_input is "" else extra_input_dim),
    )
   

    elif 'conv' in policyType:

        baseline = ZeroBaseline(env_spec=env.spec)

        policy = conv_policy(
        name="policy",
        latent_dim = ldim,
        policyType = policyType,
        env_spec=env.spec,
        init_flr=init_flr,

        hidden_nonlinearity=tf.nn.relu,
        hidden_sizes=(100, 100),                 
        extra_input_dim=(0 if extra_input is "" else extra_input_dim),
        )
       

    
    algo = algoClass(
        env=env,
        policy=policy,
        load_policy = load_policy,
        baseline=baseline,
        batch_size=fast_batch_size,  # number of trajs for alpha grad update
        max_path_length=max_path_length,
        meta_batch_size=meta_batch_size,  # number of tasks sampled for beta grad update
        num_grad_updates=num_grad_updates,  # number of alpha grad updates
        n_itr=1, #100
        make_video=False,
        use_maml=True,
        use_pooled_goals=True,
        use_corr_term=use_corr_term,
        test_on_training_goals=test_on_training_goals,
        metalearn_baseline=False,
        # metalearn_baseline=False,
        limit_demos_num=limit_demos_num,
        test_goals_mult=1,
        step_size=meta_step_size,
        plot=False,
        beta_steps=beta_steps,
        adam_curve=None,
        adam_steps=adam_steps,
        pre_std_modifier=pre_std_modifier,
        l2loss_std_mult=l2loss_std_mult,
        importance_sampling_modifier=MOD_FUNC[''],
        post_std_modifier = post_std_modifier,
        expert_trajs_dir= EXPERT_TRAJ_LOCATION, 
        expert_trajs_suffix='',
        seed=seed,
        extra_input=extra_input,
        extra_input_dim=(0 if extra_input is "" else extra_input_dim),
        plotDirPrefix = None,
        latent_dim = ldim,
        dagger = dagger , 
        expert_policy_loc = expert_policy_loc
    )
    
    algo.train()

########### Example Launcher for Vision Pushing #####################
path_to_gmps = '/home/russell/gmps/'
path_to_multiworld = '/home/russell/multiworld/'

# log_dir = '/home/russell/gmps/data/SawyerPush_repl/'
# envType = 'Push' ; annotation = 'v4-mpl-50-SAC' ; tasksFile = 'sawyer_push/push_v4' ; max_path_length = 50
#expertDataLoc = path_to_gmps + '/saved_expert_trajs/SAC-pushing/'

log_dir = '/home/russell/gmps/data/Ant_repl/'
envType = 'Ant' ; annotation = 'debug-40tasks-v2' ; tasksFile = 'rad2_quat_v2' ; max_path_length = 200
expertDataLoc = path_to_gmps+'/saved_expert_trajs/ant-quat-v2-itr400/'

#policyType = 'conv_fcBiasAda'
policyType = 'fullAda_Bias'

seed = 0 ; n_parallel = 1
ldim = 4 ; init_flr = 0.5 ; fbs = 10 ; mbs = 3  ; adamSteps = 500

load_policy = '/home/russell/data/s3/Ant-dense-quat-v2-itr400/mri_rosen/policyType_fullAda_Bias/'+\
            'ldim_4/adamSteps_500_mbs_40_fbs_50_initFlr_0.5_seed_1/itr_9.pkl'
#load_policy = '/home/russell/gmps/data/Ant_repl/rep-10tasks-v2/itr_1.pkl'
#load_policy = None
#load_policy = None
#'imgObs-Sawyer-Push-v4-mpl-50-numDemos5/Itr_250/'


variant  = {'policyType':policyType, 'ldim':ldim, 'init_flr': init_flr, 'seed' : seed , 'log_dir': log_dir+annotation,  'n_parallel' : n_parallel,
            
            'envType': envType  , 'fbs' : fbs  , 'mbs' : mbs ,  'max_path_length' : max_path_length , 'tasksFile': tasksFile , 'load_policy':load_policy , 'adam_steps': adamSteps, 'dagger': None,
            'expert_policy_loc': None , 'use_maesn': False , 'expertDataLoc': expertDataLoc }

experiment(variant)