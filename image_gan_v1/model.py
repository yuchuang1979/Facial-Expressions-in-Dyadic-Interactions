from __future__ import division
import os
import time
from glob import glob
import tensorflow as tf
import numpy as np
from six.moves import xrange
import scipy.misc

from ops import *
from utils import *
import h5py
import scipy.io as sio

class pix2pix(object):
	def __init__(self, sess, image_size=256,
				 batch_size=1, sample_size=1, output_size=256,
				 gf_dim=64, df_dim=64, L1_lambda=50, num_category = 16, num_cont = 3,
				 input_c_dim=3, output_c_dim=3, dataset_name='facades', layer_features = False,
				 checkpoint_dir=None, sample_dir=None):
		"""

		Args:
			sess: TensorFlow session
			batch_size: The size of batch. Should be specified before training.
			output_size: (optional) The resolution in pixels of the images. [256]
			gf_dim: (optional) Dimension of gen filters in first conv layer. [64]
			df_dim: (optional) Dimension of discrim filters in first conv layer. [64]
			input_c_dim: (optional) Dimension of input image color. For grayscale input, set to 1. [3]
			output_c_dim: (optional) Dimension of output image color. For grayscale input, set to 1. [3]
		"""
		self.sess = sess
		self.is_grayscale = (input_c_dim == 1)
		self.batch_size = batch_size
		self.image_size = image_size
		self.sample_size = sample_size
		self.output_size = output_size
		self.layer_features = layer_features

		self.gf_dim = gf_dim
		self.df_dim = df_dim

		self.input_c_dim = input_c_dim
		self.output_c_dim = output_c_dim

		self.L1_lambda = L1_lambda
		self.num_category = num_category
		self.num_cont = num_cont

		if dataset_name == 'shape2im':
			self.input_c_dim = 1
			self.output_c_dim = 3
			#self.is_grayscale = True
		if self.layer_features:
			print("use layer features")

		# batch normalization : deals with poor initialization helps gradient flow
		self.d_bn1 = batch_norm(name='d_bn1')
		self.d_bn2 = batch_norm(name='d_bn2')
		self.d_bn3 = batch_norm(name='d_bn3')
		self.d_bns = batch_norm(name='d_bns')

		self.g_bn_e2 = batch_norm(name='g_bn_e2')
		self.g_bn_e3 = batch_norm(name='g_bn_e3')
		self.g_bn_e4 = batch_norm(name='g_bn_e4')
		self.g_bn_e5 = batch_norm(name='g_bn_e5')
		self.g_bn_e6 = batch_norm(name='g_bn_e6')
		self.g_bn_e7 = batch_norm(name='g_bn_e7')
		self.g_bn_e8 = batch_norm(name='g_bn_e8')

		self.g_bn_d1 = batch_norm(name='g_bn_d1')
		self.g_bn_d2 = batch_norm(name='g_bn_d2')
		self.g_bn_d3 = batch_norm(name='g_bn_d3')
		self.g_bn_d4 = batch_norm(name='g_bn_d4')
		self.g_bn_d5 = batch_norm(name='g_bn_d5')
		self.g_bn_d6 = batch_norm(name='g_bn_d6')
		self.g_bn_d7 = batch_norm(name='g_bn_d7')

		self.dataset_name = dataset_name
		self.checkpoint_dir = checkpoint_dir
		self.build_model()

	def build_model(self):
		self.real_data = tf.placeholder(tf.float32,
										[self.batch_size, self.image_size, self.image_size,
										 self.input_c_dim + self.output_c_dim],
										name='real_A_and_B_images')
		self.auxi_data = tf.placeholder(tf.float32,
										[self.batch_size, self.image_size, self.image_size, self.output_c_dim],
										name='real_auxi_images')
		
		self.real_ids = tf.placeholder(tf.float32,
										[self.batch_size, 1], name = 'real_ids')
		self.auxi_ids = tf.placeholder(tf.float32,
										[self.batch_size, 1], name = 'auxi_ids')

		# A is sketch, B is image
		# output_c_dim is 3, input_c_dim is 1
		self.real_B = self.real_data[:, :, :, :self.output_c_dim]
		self.real_A = self.real_data[:, :, :, self.output_c_dim:self.input_c_dim + self.output_c_dim]
		
		self.z_cont = tf.placeholder(tf.float32, [self.batch_size, self.num_cont], name='z_cont') # should initialize in main body
		self.z_ca_r = tf.one_hot(tf.cast(tf.squeeze(self.real_ids, -1), tf.int32), depth = self.num_category) # use self.ids, should initialize in main body
		self.z_ca_a = tf.one_hot(tf.cast(tf.squeeze(self.auxi_ids, -1), tf.int32), depth = self.num_category) # use self.ids, should initialize in main body
		self.z_r = tf.concat_v2([self.z_cont, self.z_ca_r], 1) # concatenate on dimension 1 (dim 0 is for batch use)
		self.z_a = tf.concat_v2([self.z_cont, self.z_ca_a], 1) # concatenate on dimension 1 (dim 0 is for batch use)

		self.fake_B_r = self.generator(self.real_A, self.z_r, reuse=False) #generate using same shapes, but different category data. reuse?
		self.fake_B_a = self.generator(self.real_A, self.z_a, reuse=True)
		#self.real_AB = tf.concat(3, [self.real_A, self.real_B])
		#self.fake_AB = tf.concat(3, [self.real_A, self.fake_B])

		self.D_r, self.D_logits_r, self.h3_r, self.h2_r, self.h1_r, self.h0_r, self.cat_logits_r, _  = self.discriminator(self.real_B, reuse=False)
		self.D_a, self.D_logits_a, self.h3_a, self.h2_a, self.h1_a, self.h0_a, self.cat_logits_a, _  = self.discriminator(self.auxi_data, reuse=True)
		self.D__r, self.D_logits__r, self.h3__r, self.h2__r, self.h1__r, self.h0__r, self.cat_logits__r, self.cont__r = self.discriminator(self.fake_B_r, reuse=True)
		self.D__a, self.D_logits__a, self.h3__a, self.h2__a, self.h1__a, self.h0__a, self.cat_logits__a, self.cont__a = self.discriminator(self.fake_B_a, reuse=True)
		self.fake_B_sample_r = self.sampler(self.real_A, self.z_r)
		self.fake_B_sample_a = self.sampler(self.real_A, self.z_a)

		self.d_sum = tf.summary.histogram("d", self.D_r + self.D_a)
		self.d__sum = tf.summary.histogram("d_", self.D__r + self.D__a)
		self.fake_B_sum = tf.summary.image("fake_B", self.fake_B_r)

		self.d_loss_real = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits_r, targets=tf.ones_like(self.D_r))) \
							+ tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits_a, targets=tf.ones_like(self.D_a)))

		self.d_loss_fake = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits__r, targets=tf.zeros_like(self.D__r))) \
							+ tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits__a, targets=tf.zeros_like(self.D__a)))

		
		self.g_loss_r = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits__r, targets=tf.ones_like(self.D__r))) \
						+ 0.8 * self.L1_lambda * tf.reduce_mean(tf.abs(self.real_B - self.fake_B_r)) \
						+ 0.8 * self.L1_lambda * tf.reduce_mean(tf.abs(self.h3_r - self.h3__r)) \
						+ 0.8 * self.L1_lambda * tf.reduce_mean(tf.abs(self.h2_r - self.h2__r)) \
						+ 0.8 * self.L1_lambda * tf.reduce_mean(tf.abs(self.h1_r - self.h1__r)) \
						+ 0.8 * self.L1_lambda * tf.reduce_mean(tf.abs(self.h0_r - self.h0__r))

		self.g_loss_a = tf.reduce_mean(tf.nn.sigmoid_cross_entropy_with_logits(logits=self.D_logits__a, targets=tf.ones_like(self.D__a))) \
						+ self.L1_lambda * tf.reduce_mean(tf.abs(self.h3_a - self.h3__a)) \
						+ self.L1_lambda * tf.reduce_mean(tf.abs(self.h2_a - self.h2__a)) \
						+ self.L1_lambda * tf.reduce_mean(tf.abs(self.h1_a - self.h1__a)) \
						+ self.L1_lambda * tf.reduce_mean(tf.abs(self.h0_a - self.h0__a))

		
		
		self.cat_loss_real_r = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=self.cat_logits_r, labels=self.z_ca_r))
		self.cat_loss_real_a = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=self.cat_logits_a, labels=self.z_ca_a))
		self.cat_loss_fake_r = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=self.cat_logits__r, labels=self.z_ca_r))
		self.cat_loss_fake_a = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(logits=self.cat_logits__a, labels=self.z_ca_a))
		self.cat_loss = self.cat_loss_real_r + self.cat_loss_real_a + self.cat_loss_fake_r + self.cat_loss_fake_a
		
		self.con_loss_r = tf.reduce_mean(tf.square(self.cont__r-self.z_cont))
		self.con_loss_a = tf.reduce_mean(tf.square(self.cont__a-self.z_cont))
		self.con_loss = self.con_loss_r + self.con_loss_a


		self.d_loss_real_sum = tf.summary.scalar("d_loss_real", self.d_loss_real)
		self.d_loss_fake_sum = tf.summary.scalar("d_loss_fake", self.d_loss_fake)

		self.d_loss = self.d_loss_real + self.d_loss_fake
		self.g_loss = self.g_loss_r + self.g_loss_a

		self.g_loss_sum = tf.summary.scalar("g_loss", self.g_loss)
		self.d_loss_sum = tf.summary.scalar("d_loss", self.d_loss)

		t_vars = tf.trainable_variables()

		self.d_vars = [var for var in t_vars if 'd_' in var.name]
		self.g_vars = [var for var in t_vars if 'g_' in var.name]

		self.saver = tf.train.Saver()



	def sample_model_shape2im(self, sample_images, sample_ids_r, sample_ids_a, sample_z, sample_dir, epoch, idx):
		samples_r, samples_a = self.sess.run(
			[self.fake_B_sample_r, self.fake_B_sample_a],
			feed_dict={self.real_data: sample_images,
					   self.real_ids: sample_ids_r,
					   self.auxi_ids: sample_ids_a,
					   self.z_cont: sample_z}
		)
		samples = np.concatenate((samples_r, samples_a), axis=0)
		#print(samples.shape)
		#raw_input("pause here")
		save_images(samples, [8, 8],
					'./{}/train_{:02d}_{:04d}.png'.format(sample_dir, epoch, idx))
		#print("[Sample] d_loss: {:.8f}, g_loss: {:.8f}".format(d_loss, g_loss))

	

	def train(self, args):
		"""Train pix2pix"""
		d_optim = tf.train.AdamOptimizer(args.lr, beta1=args.beta1) \
						  .minimize(self.d_loss + self.cat_loss + self.con_loss, var_list=self.d_vars)
		g_optim = tf.train.AdamOptimizer(args.lr, beta1=args.beta1) \
						  .minimize(self.g_loss + self.cat_loss + self.con_loss, var_list=self.g_vars)

		init_op = tf.global_variables_initializer()
		self.sess.run(init_op)

		self.g_sum = tf.summary.merge([self.d__sum,
			self.fake_B_sum, self.d_loss_fake_sum, self.g_loss_sum])
		self.d_sum = tf.summary.merge([self.d_sum, self.d_loss_real_sum, self.d_loss_sum])
		self.writer = tf.summary.FileWriter("./logs", self.sess.graph)

		counter = 1
		start_time = time.time()

		if self.load(self.checkpoint_dir):
			print(" [*] Load SUCCESS")
		else:
			print(" [!] Load failed...")


		sp_name = "../../code/all_im_shape.mat"
		f = h5py.File(sp_name,'r')
		data_X = np.transpose(f['all_im_shape'])
		#print(data_X.dtype)
		#data_X = data_X/127.5 - 1.
		#print(data_X.dtype)
		#raw_input("aaa")
		#print(data_X.shape)
		#batch_idxs = min(len(data_X), args.train_size) // self.batch_size
		#print(len(data_X))

		batch_idxs = min(len(data_X), args.train_size) // self.batch_size

		id_name = "../../code/all_ids.mat"
		f = h5py.File(id_name,'r')
		id_X = np.transpose(f['all_ids'])

		id_A = np.copy(id_X)
		data_A = np.copy(data_X[:,:,:,0:3])

		for epoch in xrange(args.epoch):
			if self.dataset_name == 'shape2im':
				# if we have multi files (e.g. 10) in an epoch, use the following:
				#load_n = epoch % 10 + 1
				#print(load_n)
				#sp_name = "../code/good_txt/train_test/divid/image_shapec%02d.mat" % load_n
				#f = h5py.File(sp_name,'r')
				#data_X = (np.transpose(f['image_shapec'])/127.5 - 1.)
				#batch_idxs = min(len(data_X), args.train_size) // self.batch_size
				#print(len(data_X))
				#permed = np.random.permutation(len(data_X))
				#data_X = data_X[permed,:]
				#sample_images = data_X[0:self.batch_size]

				# if we have only one file in an epoch, use the following:

				permed = np.random.permutation(len(data_X))
				data_X = data_X[permed,:]
				sample_images = (data_X[0:self.batch_size])/127.5 - 1.
				id_X = id_X[permed]
				sample_ids = id_X[0:self.batch_size]
				sample_z_cont = np.random.normal(0, 1, size=(self.batch_size , self.num_cont))


				for i in xrange(0, len(id_X)):
					while 1:
						cur_id = np.random.randint(0, len(id_X))
						if id_X[cur_id] != id_X[i]:
							id_A[i] = id_X[cur_id]
							data_A[i] = data_X[cur_id, :, :, 0:3]
							break
				sample_ids_a = id_A[0:self.batch_size]

				#print(id_X[0])
				#print(id_A[0])

				#scipy.misc.imsave('sketch0.jpg', np.squeeze(data_X[0,:,:,3:4]))
				#scipy.misc.imsave('image0_x.jpg', np.squeeze(data_X[0,:,:,0:3]))
				#scipy.misc.imsave('image0_a.jpg', np.squeeze(data_A[0,:,:,:]))

				#print(id_X[1])
				#print(id_A[1])

				#raw_input("stop here")

			else:
				pass

			#print(batch_idxs)
			for idx in xrange(0, batch_idxs):
				if self.dataset_name == 'shape2im':
					batch = data_X[idx*self.batch_size:(idx+1)*self.batch_size]
					ids = id_X[idx*self.batch_size:(idx+1)*self.batch_size]
					batch_a = data_A[idx*self.batch_size:(idx+1)*self.batch_size]
					ids_a = id_X[idx*self.batch_size:(idx+1)*self.batch_size]
					z_cont = np.random.normal(0, 1, size=(self.batch_size , self.num_cont))
				else:
					pass
				
				
				batch_images = np.array((batch/127.5 - 1)).astype(np.float32)
				batch_images_a = np.array((batch_a/127.5 - 1)).astype(np.float32)
				#scipy.misc.imsave('sketch0.jpg', np.squeeze(batch_images[0,:,:,3:4]))
				#scipy.misc.imsave('image0_x.jpg', np.squeeze(batch_images[0,:,:,0:3]))
				#scipy.misc.imsave('image0_a.jpg', np.squeeze(batch_images_a[0,:,:,:]))
				#raw_input("stop here")
				# Update D network
				_, summary_str = self.sess.run([d_optim, self.d_sum],
											   feed_dict={ self.real_data: batch_images,
														   self.auxi_data: batch_images_a,
														   self.real_ids: ids,
														   self.auxi_ids: ids_a,
														   self.z_cont: z_cont})
				self.writer.add_summary(summary_str, counter)

				# Update G network
				_, summary_str = self.sess.run([g_optim, self.g_sum],
											   feed_dict={ self.real_data: batch_images,
														   self.auxi_data: batch_images_a,
														   self.real_ids: ids,
														   self.auxi_ids: ids_a,
														   self.z_cont: z_cont})
				self.writer.add_summary(summary_str, counter)

				# Run g_optim twice to make sure that d_loss does not go to zero (different from paper)
				_, summary_str = self.sess.run([g_optim, self.g_sum],
											   feed_dict={ self.real_data: batch_images,
														   self.auxi_data: batch_images_a,
														   self.real_ids: ids,
														   self.auxi_ids: ids_a,
														   self.z_cont: z_cont})
				self.writer.add_summary(summary_str, counter)

				errD_fake = self.d_loss_fake.eval({ self.real_data: batch_images,
													self.auxi_data: batch_images_a,
													self.real_ids: ids,
													self.auxi_ids: ids_a,
													self.z_cont: z_cont})
				errD_real = self.d_loss_real.eval({ self.real_data: batch_images,
													self.auxi_data: batch_images_a,
													self.real_ids: ids,
													self.auxi_ids: ids_a,
													self.z_cont: z_cont})
				errG = self.g_loss.eval({ self.real_data: batch_images,
													self.auxi_data: batch_images_a,
													self.real_ids: ids,
													self.auxi_ids: ids_a,
													self.z_cont: z_cont})

				counter += 1
				print("Epoch: [%2d] [%4d/%4d] time: %4.4f, d_loss: %.8f, g_loss: %.8f" \
					% (epoch, idx, batch_idxs,
						time.time() - start_time, errD_fake+errD_real, errG))

				if np.mod(counter, 200) == 1:
					if self.dataset_name == 'shape2im':
						self.sample_model_shape2im(sample_images,sample_ids, sample_ids_a, sample_z_cont, args.sample_dir, epoch, idx)
					else:
						pass

				if np.mod(counter, 200) == 2:
					self.save(args.checkpoint_dir, counter)

	def discriminator(self, image, y=None, reuse=False):

		with tf.variable_scope("discriminator") as scope:
			# image is 256 x 256 x (input_c_dim + output_c_dim)
			if reuse:
				tf.get_variable_scope().reuse_variables()
			else:
				assert tf.get_variable_scope().reuse == False

			h0 = lrelu(conv2d(image, self.df_dim, name='d_h0_conv'))
			#raw_input("press")
			# h0 is (128 x 128 x self.df_dim)
			h1 = lrelu(self.d_bn1(conv2d(h0, self.df_dim*2, name='d_h1_conv')))
			# h1 is (64 x 64 x self.df_dim*2)
			h2 = lrelu(self.d_bn2(conv2d(h1, self.df_dim*4, name='d_h2_conv')))
			# h2 is (32x 32 x self.df_dim*4)
			h3 = lrelu(self.d_bn3(conv2d(h2, self.df_dim*8, d_h=1, d_w=1, name='d_h3_conv')))
			# h3 is (16 x 16 x self.df_dim*8)
			h3_f = tf.reshape(h3, [self.batch_size, -1])
			h4 = linear(h3_f, 1, 'd_h4_lin')
			h_share = lrelu(self.d_bns(linear(h3_f, 128, 'd_hs_lin')))

			# recog_cat is used for recognizing categories
			recog_cat = linear(h_share, self.num_category, 'd_cat_lin')
			# recog_con is used for recognizing continous variables
			recog_con = linear(h_share, self.num_cont, 'd_con_lin')

			return tf.nn.sigmoid(h4), h4, h3, h2, h1, h0, recog_cat, tf.nn.sigmoid(recog_con)

	def generator(self, image, z, y=None, reuse=False):
		with tf.variable_scope("generator") as scope:

			if reuse:
				tf.get_variable_scope().reuse_variables()
			else:
				assert tf.get_variable_scope().reuse == False

			s = self.output_size
			s2, s4, s8, s16, s32, s64, s128 = int(s/2), int(s/4), int(s/8), int(s/16), int(s/32), int(s/64), int(s/128)

			zb = tf.reshape(z, [self.batch_size, int(1), int(1), self.num_category + self.num_cont])
			# image is (256 x 256 x input_c_dim)
			e1 = conv2d(image, self.gf_dim, name='g_e1_conv')
			e1 = conv_cond_concat(e1, zb)
			# e1 is (128 x 128 x self.gf_dim)
			e2 = self.g_bn_e2(conv2d(lrelu(e1), self.gf_dim*2, name='g_e2_conv'))
			e2 = conv_cond_concat(e2, zb)
			# e2 is (64 x 64 x self.gf_dim*2 + )
			e3 = self.g_bn_e3(conv2d(lrelu(e2), self.gf_dim*4, name='g_e3_conv'))
			e3 = conv_cond_concat(e3, zb)
			# e3 is (32 x 32 x self.gf_dim*4 + )
			e4 = self.g_bn_e4(conv2d(lrelu(e3), self.gf_dim*8, name='g_e4_conv'))
			e4 = conv_cond_concat(e4, zb)
			# e4 is (16 x 16 x self.gf_dim*8 + )
			e5 = self.g_bn_e5(conv2d(lrelu(e4), self.gf_dim*8, name='g_e5_conv'))
			e5 = conv_cond_concat(e5, zb)
			# e5 is (8 x 8 x self.gf_dim*8 + )
			e6 = self.g_bn_e6(conv2d(lrelu(e5), self.gf_dim*8, name='g_e6_conv'))
			e6 = conv_cond_concat(e6, zb)
			# e6 is (4 x 4 x self.gf_dim*8 + )
			e7 = self.g_bn_e7(conv2d(lrelu(e6), self.gf_dim*8, name='g_e7_conv'))
			e7 = conv_cond_concat(e7, zb)
			# e7 is (2 x 2 x self.gf_dim*8 + )
			e8 = self.g_bn_e8(conv2d(lrelu(e7), self.gf_dim*8, name='g_e8_conv'))
			# e8 is (1 x 1 x self.gf_dim*8 + )

			
			e8 = tf.concat_v2([e8, zb], 3)

			self.d1, self.d1_w, self.d1_b = deconv2d(tf.nn.relu(e8),
				[self.batch_size, s128, s128, self.gf_dim*8], name='g_d1', with_w=True)
			d1 = tf.nn.dropout(self.g_bn_d1(self.d1), 0.5)
			#d1 = tf.concat(3, [d1, e7])
			d1 = tf.concat_v2([d1, e7], 3)
			#raw_input("press")
			
			# d1 is (2 x 2 x self.gf_dim*8*2)

			self.d2, self.d2_w, self.d2_b = deconv2d(tf.nn.relu(d1),
				[self.batch_size, s64, s64, self.gf_dim*8], name='g_d2', with_w=True)
			d2 = tf.nn.dropout(self.g_bn_d2(self.d2), 0.5)
			d2 = tf.concat_v2([d2, e6], 3)
			#d2 = conv_cond_concat(d2, zb)
			#d2 = tf.concat(3, [d2, e6])
			# d2 is (4 x 4 x self.gf_dim*8*2)

			self.d3, self.d3_w, self.d3_b = deconv2d(tf.nn.relu(d2),
				[self.batch_size, s32, s32, self.gf_dim*8], name='g_d3', with_w=True)
			d3 = tf.nn.dropout(self.g_bn_d3(self.d3), 0.5)
			d3 = tf.concat_v2([d3, e5], 3)
			#d3 = conv_cond_concat(d3, zb)
			#d3 = tf.concat(3, [d3, e5])
			# d3 is (8 x 8 x self.gf_dim*8*2)

			self.d4, self.d4_w, self.d4_b = deconv2d(tf.nn.relu(d3),
				[self.batch_size, s16, s16, self.gf_dim*8], name='g_d4', with_w=True)
			d4 = self.g_bn_d4(self.d4)
			d4 = tf.concat_v2([d4, e4], 3)
			#d4 = conv_cond_concat(d4, zb)
			#d4 = tf.concat(3, [d4, e4])
			# d4 is (16 x 16 x self.gf_dim*8*2)

			self.d5, self.d5_w, self.d5_b = deconv2d(tf.nn.relu(d4),
				[self.batch_size, s8, s8, self.gf_dim*4], name='g_d5', with_w=True)
			d5 = self.g_bn_d5(self.d5)
			d5 = tf.concat_v2([d5, e3], 3)
			#d5 = conv_cond_concat(d5, zb)
			#d5 = tf.concat(3, [d5, e3])
			# d5 is (32 x 32 x self.gf_dim*4*2)

			self.d6, self.d6_w, self.d6_b = deconv2d(tf.nn.relu(d5),
				[self.batch_size, s4, s4, self.gf_dim*2], name='g_d6', with_w=True)
			d6 = self.g_bn_d6(self.d6)
			d6 = tf.concat_v2([d6, e2], 3)
			#d6 = conv_cond_concat(d6, zb)
			#d6 = tf.concat(3, [d6, e2])
			# d6 is (64 x 64 x self.gf_dim*2*2)

			self.d7, self.d7_w, self.d7_b = deconv2d(tf.nn.relu(d6),
				[self.batch_size, s2, s2, self.gf_dim], name='g_d7', with_w=True)
			d7 = self.g_bn_d7(self.d7)
			d7 = tf.concat_v2([d7, e1], 3)
			#d7 = conv_cond_concat(d7, zb)
			#d7 = tf.concat(3, [d7, e1])
			# d7 is (128 x 128 x self.gf_dim*1*2)

			self.d8, self.d8_w, self.d8_b = deconv2d(tf.nn.relu(d7),
				[self.batch_size, s, s, self.output_c_dim], name='g_d8', with_w=True)
			# d8 is (256 x 256 x output_c_dim)

			return tf.nn.tanh(self.d8)

	def sampler(self, image, z, y=None):

		with tf.variable_scope("generator") as scope:
			scope.reuse_variables()

			s = self.output_size
			s2, s4, s8, s16, s32, s64, s128 = int(s/2), int(s/4), int(s/8), int(s/16), int(s/32), int(s/64), int(s/128)
			zb = tf.reshape(z, [self.batch_size, int(1), int(1), self.num_category + self.num_cont])
			# image is (256 x 256 x input_c_dim)
			e1 = conv2d(image, self.gf_dim, name='g_e1_conv')
			e1 = conv_cond_concat(e1, zb)
			# e1 is (128 x 128 x self.gf_dim)
			e2 = self.g_bn_e2(conv2d(lrelu(e1), self.gf_dim*2, name='g_e2_conv'))
			e2 = conv_cond_concat(e2, zb)
			# e2 is (64 x 64 x self.gf_dim*2)
			e3 = self.g_bn_e3(conv2d(lrelu(e2), self.gf_dim*4, name='g_e3_conv'))
			e3 = conv_cond_concat(e3, zb)
			# e3 is (32 x 32 x self.gf_dim*4)
			e4 = self.g_bn_e4(conv2d(lrelu(e3), self.gf_dim*8, name='g_e4_conv'))
			e4 = conv_cond_concat(e4, zb)
			# e4 is (16 x 16 x self.gf_dim*8)
			e5 = self.g_bn_e5(conv2d(lrelu(e4), self.gf_dim*8, name='g_e5_conv'))
			e5 = conv_cond_concat(e5, zb)
			# e5 is (8 x 8 x self.gf_dim*8)
			e6 = self.g_bn_e6(conv2d(lrelu(e5), self.gf_dim*8, name='g_e6_conv'))
			e6 = conv_cond_concat(e6, zb)
			# e6 is (4 x 4 x self.gf_dim*8)
			e7 = self.g_bn_e7(conv2d(lrelu(e6), self.gf_dim*8, name='g_e7_conv'))
			e7 = conv_cond_concat(e7, zb)
			# e7 is (2 x 2 x self.gf_dim*8)
			e8 = self.g_bn_e8(conv2d(lrelu(e7), self.gf_dim*8, name='g_e8_conv'))
			# e8 is (1 x 1 x self.gf_dim*8)

			e8 = tf.concat_v2([e8, zb], 3)

			self.d1, self.d1_w, self.d1_b = deconv2d(tf.nn.relu(e8),
				[self.batch_size, s128, s128, self.gf_dim*8], name='g_d1', with_w=True)
			d1 = tf.nn.dropout(self.g_bn_d1(self.d1), 0.5)
			d1 = tf.concat_v2([d1, e7], 3)
			#d1 = tf.concat(3, [d1, e7])
			# d1 is (2 x 2 x self.gf_dim*8*2)

			# without dropout is like this:
			#self.d1, self.d1_w, self.d1_b = deconv2d(tf.nn.relu(e8),
			#    [self.batch_size, s128, s128, self.gf_dim*8], name='g_d1', with_w=True)
			#d1 = self.g_bn_d1(self.d1)
			#d1 = tf.concat_v2([d1, e7], 3)

			self.d2, self.d2_w, self.d2_b = deconv2d(tf.nn.relu(d1),
				[self.batch_size, s64, s64, self.gf_dim*8], name='g_d2', with_w=True)
			d2 = tf.nn.dropout(self.g_bn_d2(self.d2), 0.5)
			d2 = tf.concat_v2([d2, e6], 3)
			#d2 = tf.concat(3, [d2, e6])
			# d2 is (4 x 4 x self.gf_dim*8*2)

			self.d3, self.d3_w, self.d3_b = deconv2d(tf.nn.relu(d2),
				[self.batch_size, s32, s32, self.gf_dim*8], name='g_d3', with_w=True)
			d3 = tf.nn.dropout(self.g_bn_d3(self.d3), 0.5)
			d3 = tf.concat_v2([d3, e5], 3)
			#d3 = tf.concat(3, [d3, e5])
			# d3 is (8 x 8 x self.gf_dim*8*2)

			self.d4, self.d4_w, self.d4_b = deconv2d(tf.nn.relu(d3),
				[self.batch_size, s16, s16, self.gf_dim*8], name='g_d4', with_w=True)
			d4 = self.g_bn_d4(self.d4)
			d4 = tf.concat_v2([d4, e4], 3)
			#d4 = tf.concat(3, [d4, e4])
			# d4 is (16 x 16 x self.gf_dim*8*2)

			self.d5, self.d5_w, self.d5_b = deconv2d(tf.nn.relu(d4),
				[self.batch_size, s8, s8, self.gf_dim*4], name='g_d5', with_w=True)
			d5 = self.g_bn_d5(self.d5)
			d5 = tf.concat_v2([d5, e3], 3)
			#d5 = tf.concat(3, [d5, e3])
			# d5 is (32 x 32 x self.gf_dim*4*2)

			self.d6, self.d6_w, self.d6_b = deconv2d(tf.nn.relu(d5),
				[self.batch_size, s4, s4, self.gf_dim*2], name='g_d6', with_w=True)
			d6 = self.g_bn_d6(self.d6)
			d6 = tf.concat_v2([d6, e2], 3)
			#d6 = tf.concat(3, [d6, e2])
			# d6 is (64 x 64 x self.gf_dim*2*2)

			self.d7, self.d7_w, self.d7_b = deconv2d(tf.nn.relu(d6),
				[self.batch_size, s2, s2, self.gf_dim], name='g_d7', with_w=True)
			d7 = self.g_bn_d7(self.d7)
			d7 = tf.concat_v2([d7, e1], 3)
			#d7 = tf.concat(3, [d7, e1])
			# d7 is (128 x 128 x self.gf_dim*1*2)

			self.d8, self.d8_w, self.d8_b = deconv2d(tf.nn.relu(d7),
				[self.batch_size, s, s, self.output_c_dim], name='g_d8', with_w=True)
			# d8 is (256 x 256 x output_c_dim)

			return tf.nn.tanh(self.d8)


	def save(self, checkpoint_dir, step):
		model_name = "pix2pix.model"
		model_dir = "%s_%s_%s" % (self.dataset_name, self.batch_size, self.output_size)
		checkpoint_dir = os.path.join(checkpoint_dir, model_dir)

		if not os.path.exists(checkpoint_dir):
			os.makedirs(checkpoint_dir)

		self.saver.save(self.sess,
						os.path.join(checkpoint_dir, model_name),
						global_step=step)

	def load(self, checkpoint_dir):
		print(" [*] Reading checkpoint...")

		model_dir = "%s_%s_%s" % (self.dataset_name, self.batch_size, self.output_size)
		checkpoint_dir = os.path.join(checkpoint_dir, model_dir)

		ckpt = tf.train.get_checkpoint_state(checkpoint_dir)
		if ckpt and ckpt.model_checkpoint_path:
			ckpt_name = os.path.basename(ckpt.model_checkpoint_path)
			self.saver.restore(self.sess, os.path.join(checkpoint_dir, ckpt_name))
			return True
		else:
			return False


	def test_gen(self, args):
		init_op = tf.global_variables_initializer()
		self.sess.run(init_op)

		if self.load(self.checkpoint_dir):
			print(" [*] Load SUCCESS")
		else:
			print(" [!] Load failed...")

		for j in xrange(1):
			
			shapeIm_mat_name = "../../Ben_data/test_user_082817/{:02d}shapeIm.mat".format(j + 1)
			ids_mat_name = "../../Ben_data/test_user_082817/{:02d}ids.mat".format(j + 1)
			f = h5py.File(shapeIm_mat_name,'r')
			shapeIm = (np.transpose(f['ImShape'])/127.5 - 1.)
			f = h5py.File(ids_mat_name,'r')
			ids = np.transpose(f['ids'])
			old_len = len(shapeIm)

			pad_len = self.batch_size - (len(shapeIm) % self.batch_size)
			pad_img = np.array([shapeIm[-1] for i in xrange(pad_len)])
			pad_ids = np.array([ids[-1] for i in xrange(pad_len)])
			z_cont = [0, 0, 0]
			pad_zs = np.squeeze([z_cont for i in xrange(self.batch_size)])
			shapeIm = np.concatenate((shapeIm, pad_img), axis = 0)
			ids = np.concatenate((ids, pad_ids), axis = 0)
			batch_idxs = min(len(shapeIm), args.train_size) // self.batch_size
			k = 0
			for idx in xrange(0, batch_idxs):
				batch_shapeIm = shapeIm[idx*self.batch_size:(idx+1)*self.batch_size]
				batch_ids = ids[idx*self.batch_size:(idx+1)*self.batch_size]
				sample_outputs = self.sess.run(self.fake_B_sample, feed_dict={self.real_data: batch_shapeIm,self.ids: batch_ids,self.z_cont: pad_zs})
				sample_outputs = inverse_transform(sample_outputs)
				for ind in xrange(0, self.batch_size):
					if k > old_len:
						break
					directory = './test/sequence/{:02d}/'.format(j + 1)
					try:
						os.stat(directory)
					except:
						os.mkdir(directory)

					out_filename = directory + '{:05d}.jpg'.format(k)
					scipy.misc.imsave(out_filename,np.squeeze(sample_outputs[ind,:,:,:]))
					k = k + 1