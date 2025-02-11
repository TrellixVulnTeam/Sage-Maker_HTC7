# Copyright 2017 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You
# may not use this file except in compliance with the License. A copy of
# the License is located at
#
#     http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific
# language governing permissions and limitations under the License.
from __future__ import absolute_import

import os
import time

import pytest
import numpy

from sagemaker.chainer.defaults import CHAINER_VERSION
from sagemaker.chainer.estimator import Chainer
from sagemaker.chainer.model import ChainerModel
from sagemaker.utils import sagemaker_timestamp
from tests.integ import DATA_DIR
from tests.integ.timeout import timeout, timeout_and_delete_endpoint_by_name


@pytest.fixture(scope='module')
def chainer_training_job(sagemaker_session, chainer_full_version):
    return _run_mnist_training_job(sagemaker_session, "ml.c4.xlarge", 1, chainer_full_version)


def test_distributed_cpu_training(sagemaker_session, chainer_full_version):
    _run_mnist_training_job(sagemaker_session, "ml.c4.xlarge", 2, chainer_full_version)


def test_distributed_gpu_training(sagemaker_session, chainer_full_version):
    _run_mnist_training_job(sagemaker_session, "ml.p2.xlarge", 2, chainer_full_version)


def test_training_with_additional_hyperparameters(sagemaker_session, chainer_full_version):
    with timeout(minutes=15):
        script_path = os.path.join(DATA_DIR, 'chainer_mnist', 'mnist.py')
        data_path = os.path.join(DATA_DIR, 'chainer_mnist')

        chainer = Chainer(entry_point=script_path, role='SageMakerRole',
                          train_instance_count=1, train_instance_type="ml.c4.xlarge",
                          framework_version=chainer_full_version,
                          sagemaker_session=sagemaker_session, hyperparameters={'epochs': 1},
                          use_mpi=True,
                          num_processes=2,
                          process_slots_per_host=2,
                          additional_mpi_options="-x NCCL_DEBUG=INFO")

        train_input = chainer.sagemaker_session.upload_data(path=os.path.join(data_path, 'train'),
                                                            key_prefix='integ-test-data/chainer_mnist/train')
        test_input = chainer.sagemaker_session.upload_data(path=os.path.join(data_path, 'test'),
                                                           key_prefix='integ-test-data/chainer_mnist/test')

        chainer.fit({'train': train_input, 'test': test_input})
        return chainer.latest_training_job.name


@pytest.mark.continuous_testing
def test_attach_deploy(chainer_training_job, sagemaker_session):
    endpoint_name = 'test-chainer-attach-deploy-{}'.format(sagemaker_timestamp())

    with timeout_and_delete_endpoint_by_name(endpoint_name, sagemaker_session, minutes=20):
        estimator = Chainer.attach(chainer_training_job, sagemaker_session=sagemaker_session)
        predictor = estimator.deploy(1, 'ml.m4.xlarge', endpoint_name=endpoint_name)
        _predict_and_assert(predictor)


def test_deploy_model(chainer_training_job, sagemaker_session):
    endpoint_name = 'test-chainer-deploy-model-{}'.format(sagemaker_timestamp())
    with timeout_and_delete_endpoint_by_name(endpoint_name, sagemaker_session, minutes=20):
        desc = sagemaker_session.sagemaker_client.describe_training_job(TrainingJobName=chainer_training_job)
        model_data = desc['ModelArtifacts']['S3ModelArtifacts']
        script_path = os.path.join(DATA_DIR, 'chainer_mnist', 'mnist.py')
        model = ChainerModel(model_data, 'SageMakerRole', entry_point=script_path, sagemaker_session=sagemaker_session)
        predictor = model.deploy(1, "ml.m4.xlarge", endpoint_name=endpoint_name)
        _predict_and_assert(predictor)


def test_async_fit(sagemaker_session):
    endpoint_name = 'test-chainer-attach-deploy-{}'.format(sagemaker_timestamp())

    with timeout(minutes=5):
        training_job_name = _run_mnist_training_job(sagemaker_session, "ml.c4.xlarge", 1,
                                                    chainer_full_version=CHAINER_VERSION, wait=False)

        print("Waiting to re-attach to the training job: %s" % training_job_name)
        time.sleep(20)

    with timeout_and_delete_endpoint_by_name(endpoint_name, sagemaker_session, minutes=35):
        print("Re-attaching now to: %s" % training_job_name)
        estimator = Chainer.attach(training_job_name=training_job_name, sagemaker_session=sagemaker_session)
        predictor = estimator.deploy(1, "ml.c4.xlarge", endpoint_name=endpoint_name)
        _predict_and_assert(predictor)


def test_failed_training_job(sagemaker_session, chainer_full_version):
    with timeout(minutes=15):
        script_path = os.path.join(DATA_DIR, 'chainer_mnist', 'failure_script.py')
        data_path = os.path.join(DATA_DIR, 'chainer_mnist')

        chainer = Chainer(entry_point=script_path, role='SageMakerRole',
                          framework_version=chainer_full_version,
                          train_instance_count=1, train_instance_type='ml.c4.xlarge',
                          sagemaker_session=sagemaker_session)

        train_input = chainer.sagemaker_session.upload_data(path=os.path.join(data_path, 'train'),
                                                            key_prefix='integ-test-data/chainer_mnist/train')

        with pytest.raises(ValueError):
            chainer.fit(train_input)


def _run_mnist_training_job(sagemaker_session, instance_type, instance_count,
                            chainer_full_version, wait=True):
    with timeout(minutes=15):

        script_path = os.path.join(DATA_DIR, 'chainer_mnist', 'mnist.py') if instance_type == 1 else \
            os.path.join(DATA_DIR, 'chainer_mnist', 'distributed_mnist.py')

        data_path = os.path.join(DATA_DIR, 'chainer_mnist')

        chainer = Chainer(entry_point=script_path, role='SageMakerRole',
                          framework_version=chainer_full_version,
                          train_instance_count=instance_count, train_instance_type=instance_type,
                          sagemaker_session=sagemaker_session, hyperparameters={'epochs': 1})

        train_input = chainer.sagemaker_session.upload_data(path=os.path.join(data_path, 'train'),
                                                            key_prefix='integ-test-data/chainer_mnist/train')
        test_input = chainer.sagemaker_session.upload_data(path=os.path.join(data_path, 'test'),
                                                           key_prefix='integ-test-data/chainer_mnist/test')

        chainer.fit({'train': train_input, 'test': test_input}, wait=wait)
        return chainer.latest_training_job.name


def _predict_and_assert(predictor):
    batch_size = 100
    data = numpy.zeros((batch_size, 784), dtype='float32')
    output = predictor.predict(data)
    assert len(output) == batch_size

    data = numpy.zeros((batch_size, 1, 28, 28), dtype='float32')
    output = predictor.predict(data)
    assert len(output) == batch_size

    data = numpy.zeros((batch_size, 28, 28), dtype='float32')
    output = predictor.predict(data)
    assert len(output) == batch_size
