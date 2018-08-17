# -*- coding: utf-8 -*-
"""
General purpose THEMIS MCMC fitter

@author: Tom Williams

v1.00: 20180817.
"""

#Ensure python3 compatibility
from __future__ import absolute_import, print_function, division

#For plotting
import matplotlib
matplotlib.rcParams['font.family'] = 'Latin Modern Roman'
import matplotlib.pyplot as plt
plt.rcParams['mathtext.fontset'] = 'cm'
import corner

#OS I/O stuff
import os
import dill
import tarfile
from multiprocessing import Pool
import pandas as pd

import numpy as np
from scipy.constants import h,k,c
import emcee
import time
import datetime
from tqdm import tqdm

def read_sed(isrf,
             alpha):
    
    #Read in the SED that corresponds to this
    #combination of ISRF strength and alpha 
    #(rounded to nearest 0.01)
    
    if '%.2f' % isrf in ['-0.00']:
        isrf = np.abs(isrf)

    small_grains = sCM20_df['%.2f,%.2f' % (alpha,isrf)].values.copy()
    large_grains = lCM20_df['%.2f,%.2f' % (alpha,isrf)].values.copy()
    silicates = aSilM5_df['%.2f,%.2f' % (alpha,isrf)].values.copy()
    
    #Convert these into units more like Jy -- divide by Hz
    
    small_grains /= frequency
    large_grains /= frequency
    silicates /= frequency
    
    return small_grains,large_grains,silicates

def filter_convolve_not_fit(flux,
                            keys):
    
    #Convolve this SED with the various filters we have to give
    #a monochromatic flux
 
    filter_fluxes = []
    
    for key in keys:
                 
        #Convolve MBB with filter
        
        filter_flux = np.interp(filter_dict[key][0],wavelength,flux)
                 
        filter_fluxes.append( np.abs( (np.trapz(filter_dict[key][1]*filter_flux,filter_dict[key][0])/
                                      np.trapz(filter_dict[key][1],filter_dict[key][0])) ) )
    
    return np.array(filter_fluxes)

def filter_convolve(flux):
    
    #Convolve this SED with the various filters we have to give
    #a monochromatic flux
 
    filter_fluxes = []
    
    for key in keys:
                 
        #Convolve MBB with filter
        
        filter_flux = np.interp(filter_dict[key][0],wavelength,flux)
                 
        filter_fluxes.append( np.abs( (np.trapz(filter_dict[key][1]*filter_flux,filter_dict[key][0])/
                                      np.trapz(filter_dict[key][1],filter_dict[key][0])) ) )
    
    return np.array(filter_fluxes)

def lnprob(theta,
           obs_flux,obs_error,
           stars):
    
    lp = priors(theta)
    
    if not np.isfinite(lp):
        return -np.inf
    return lp + lnlike(theta,
                       obs_flux,obs_error,
                       stars)

def priors(theta):
    
    #log_ISRF must be between -1 and 3.5.
    #alpha_sCM20 must be between 2.6 and 5.4.
    #Multiplicative factors must be greater than 0
    
    isrf,\
        omega_star,\
        alpha,\
        y_sCM20,\
        y_lCM20,\
        y_aSilM5,\
        dust_scaling = theta
    
    if -1 <= isrf <= 3.5 and \
        omega_star > 0 and \
        2.6<=alpha<=5.4 and \
        y_sCM20 > 0 and \
        y_lCM20 > 0 and \
        y_aSilM5 > 0 and \
        dust_scaling > 0:
        return 0.0
    else:
        return -np.inf
    
def lnlike(theta,
           obs_flux,obs_error,
           stars):
    
    isrf,\
        omega_star,\
        alpha,\
        y_sCM20,\
        y_lCM20,\
        y_aSilM5,\
        dust_scaling = theta
        
    small_grains,\
        large_grains,\
        silicates = read_sed(isrf,
                             alpha)    
    
    #Scale everything accordingly
    
    total = dust_scaling*y_sCM20*small_grains+\
            dust_scaling*y_lCM20*large_grains+\
            dust_scaling*y_aSilM5*silicates+omega_star*stars
            
    filter_fluxes = filter_convolve(total)
    
    #Build up a matrix for the various uncertainties
    
    rms_err = np.matrix(np.zeros([len(obs_flux),len(obs_flux)]))
    
    for i in range(len(obs_error)):
        rms_err[i,i] = obs_error[i]**2
        
    #Uncorrelated calibration errors
        
    uncorr_err = np.matrix(np.zeros([len(obs_flux),len(obs_flux)]))
    
    i = 0
    
    for key in keys:
        
        uncorr_err[i,i] = (filter_df[key][1]*obs_flux[i])**2
        
        i += 1
        
    #And finally, correlated calibration errors
    
    corr_err = np.matrix(np.zeros([len(obs_flux),len(obs_flux)]))
    
    for i in range(len(obs_flux)):
        for j in range(len(obs_flux)):
            
            corr_err[i,j] = obs_flux[i]*obs_flux[j]* \
                            corr_uncert_df[keys[j]][corr_uncert_df.index[corr_uncert_df['name'] == keys[j]][0]]* \
                            corr_uncert_df[keys[i]][corr_uncert_df.index[corr_uncert_df['name'] == keys[i]][0]]
    
    total_err = rms_err+uncorr_err+corr_err
    
    flux_diff = (filter_fluxes-obs_flux)[np.newaxis]
    
    chisq = flux_diff*total_err.I*flux_diff.T
    
    likelihood = -0.5*chisq
    
    return likelihood

start_time = time.time()
os.chdir(os.getcwd())

#Define whether we want to output skirt dust code snippets and dustEM
#GRAIN.dat files. Also if we want to plot

skirt_output = True
dustem_output = True
plot = True

#Create folders for sample pickle jars and plots, if they don't exits

if not os.path.exists('plots'):
    os.mkdir('plots')
if not os.path.exists('samples'):
    os.mkdir('samples')
if skirt_output and not os.path.exists('skirt_output'):
    os.mkdir('skirt_output')
if dustem_output and not os.path.exists('dustem_output'):
    os.mkdir('dustem_output')
    
#Read in the DustEM grid

sCM20_df = pd.read_hdf('models.h5','sCM20')
lCM20_df = pd.read_hdf('models.h5','lCM20')
aSilM5_df = pd.read_hdf('models.h5','aSilM5')

#Read in the Pandas dataframes

flux_df = pd.read_csv('fluxes.csv')
filter_df = pd.read_csv('filters.csv')
corr_uncert_df = pd.read_csv('corr_uncert.csv')

#Define the wavelength grid (given by the dustEM output)

wavelength = sCM20_df['wavelength'].values.copy()
frequency = 3e8/(wavelength*1e-6)

default_total = sCM20_df['5.00,0.00'].values.copy()+\
                lCM20_df['5.00,0.00'].values.copy()+\
                aSilM5_df['5.00,0.00'].values.copy()

#Create a dictionary of the filters

filter_dict = {}

for filter_name in filter_df.dtypes.index[1:]:
    
    filter_wavelength,transmission = np.loadtxt('filters/'+filter_name+'.dat',
                                     unpack=True)
    
    filter_wavelength /= 1e4
    transmission /= np.max(transmission)
    
    filter_dict[filter_name] = filter_wavelength,transmission

for gal_row in range(len(flux_df)):
    
    distance = flux_df['dist_best'][gal_row]
    gal_name = flux_df['name'][gal_row]
    
    #Pull out fluxes, flux errors and wavebands
    
    obs_wavelength = []
    obs_flux = []
    obs_error = []
    keys = []
    
    obs_wavelength_not_fit = []
    obs_flux_not_fit = []
    obs_error_not_fit = []
    keys_not_fit = []
    
    for key in filter_dict:
        
        try:
                        
            if np.isnan(flux_df[key][gal_row]) == False:
                
                if flux_df[key][gal_row] > 0:
                    
                    #Fit only the data with no flags
                    
                    if pd.isnull(flux_df[key+'_flag'][gal_row]):
                
                        obs_wavelength.append(filter_df[key][0])
                        obs_flux.append(flux_df[key][gal_row])
                        obs_error.append(flux_df[key+'_err'][gal_row])
                        keys.append(key)
                        
                    else:
                        
                        obs_wavelength_not_fit.append(filter_df[key][0])
                        obs_flux_not_fit.append(flux_df[key][gal_row])
                        obs_error_not_fit.append(flux_df[key+'_err'][gal_row])
                        keys_not_fit.append(key)                        
                
        except KeyError:
            pass
        
    obs_wavelength = np.array(obs_wavelength)
    obs_flux = np.array(obs_flux)
    obs_error = np.array(obs_error)
    
    obs_wavelength_not_fit = np.array(obs_wavelength_not_fit)
    obs_flux_not_fit = np.array(obs_flux_not_fit)
    obs_error_not_fit = np.array(obs_error_not_fit)
    
    #Only fit if we cover the entire SED adequately. This means either 3.4
    #or 3.6, Spizer 8 or WISE 12 or IRAS 12, MIPS 24 or WISE 22 or IRAS 25,
    #MIPS 70 or PACS 70 or IRAS 60, PACS 100 or IRAS 100, MIPS 160 or PACS 160,
    #SPIRE 250, SPIRE 350 or Planck 350, SPIRE 500 or Planck 550.
    
    if 'Spitzer_3.6' not in keys and 'WISE_3.4' not in keys:
        print('Insufficient points to fit '+gal_name)
        continue
    if 'Spitzer_8.0' not in keys and 'WISE_12' not in keys and 'IRAS_12' not in keys:
        print('Insufficient points to fit '+gal_name)
        continue
    if 'Spitzer_24' not in keys and 'WISE_22' not in keys and 'IRAS_25' not in keys:
        print('Insufficient points to fit '+gal_name)
        continue
    if 'Spitzer_70' not in keys and 'PACS_70' not in keys and 'IRAS_60' not in keys:
        print('Insufficient points to fit '+gal_name)
        continue
    if 'PACS_100' not in keys and 'IRAS_100' not in keys:
        print('Insufficient points to fit '+gal_name)
        continue
    if 'Spitzer_160' not in keys and 'PACS_160' not in keys:
        print('Insufficient points to fit '+gal_name)
        continue
    if 'SPIRE_250' not in keys:
        print('Insufficient points to fit '+gal_name)
        continue
    if 'SPIRE_350' not in keys and 'Planck_350' not in keys:
        print('Insufficient points to fit '+gal_name)
        continue
    if 'SPIRE_500' not in keys and 'Planck_550' not in keys:
        print('Insufficient points to fit '+gal_name)
        continue
    
    #Create a blackbody of 5000K to represent the stars, and lock this
    #at the 3.6micron IRAC flux (or the 3.4 WISE flux if not available)
    
    stars = 2*h*frequency**3/c**2 * (np.exp( (h*frequency)/(k*5000) ) -1)**-1
    
    try:
        if not np.isnan(flux_df['Spitzer_3.6'][gal_row]):
            idx = np.where(np.abs(wavelength-3.6) == np.min(np.abs(wavelength-3.6)))
            ratio = flux_df['Spitzer_3.6'][gal_row]/stars[idx]
        else:
            idx = np.where(np.abs(wavelength-3.4) == np.min(np.abs(wavelength-3.4)))
            ratio = flux_df['WISE_3.4'][gal_row]/stars[idx]
    except KeyError:
        idx = np.where(np.abs(wavelength-3.4) == np.min(np.abs(wavelength-3.4)))
        ratio = flux_df['WISE_3.4'][gal_row]/stars[idx]
    
    stars *= ratio
    
    #Set an initial guess for the scaling variable. Lock this by a default THEMIS SED
    #to the 250 micron flux
    
    idx = np.where(np.abs(wavelength-250) == np.min(np.abs(wavelength-250)))
    initial_dust_scaling = flux_df['SPIRE_250'][gal_row]/default_total[idx] * (3e8/250e-6)
    
    #Read in the pickle jar if it exists, else do the fitting
    
    if os.path.exists('samples/'+gal_name+'_samples.hkl'):
        
        print('Reading in '+gal_name+' pickle jar')
        
        with open('samples/'+gal_name+'_samples.hkl', 'rb') as samples_dj:
            samples = dill.load(samples_dj)    
            
    else:
    
        #Set up the MCMC. We have 7 free parameters.
        #ISRF strength,
        #Stellar scaling,
        #Power-law slope for small carbon grains,
        #deviation from default abundance of the small- and large-carbon grains
        #and silicates,
        #and the overall scaling factor for the dust grains.
        
        #Set the initial guesses for the slope and abundances at the default 
        #THEMIS parameters. The overall scaling is given by the ratio to 250 micron
        #earlier, and since we've already normalised the stellar parameter set this
        #to 1. The ISRF is 10^0, i.e. MW default.
                 
        ndim,nwalkers = (7,500)
         
        pos = []
         
        for i in range(nwalkers):
            
            isrf_var = np.random.normal(loc=0,scale=1e-2)
            omega_star_var = np.abs(np.random.normal(loc=1,scale=1e-2))
            alpha_var = np.abs(np.random.normal(loc=5,scale=1e-2*5))
            y_sCM20_var = np.abs(np.random.normal(loc=1,scale=1e-2))
            y_lCM20_var = np.abs(np.random.normal(loc=1,scale=1e-2))
            y_aSilM5_var = np.abs(np.random.normal(loc=1,scale=1e-2))
            dust_scaling_var = np.abs(np.random.normal(loc=initial_dust_scaling,
                                                  scale=initial_dust_scaling*1e-2))
        
            pos.append([isrf_var,
                        omega_star_var,
                        alpha_var,
                        y_sCM20_var,
                        y_lCM20_var,
                        y_aSilM5_var,
                        dust_scaling_var])
            
        #Run this MCMC. Since emcee pickles any arguments passed to it, use as few
        #as possible and rely on global variables instead!
        
        pool = Pool()
        
        sampler = emcee.EnsembleSampler(nwalkers, 
                                        ndim, 
                                        lnprob, 
                                        args=(obs_flux,obs_error,
                                              stars),
                                        pool=pool)
         
        #500 steps for the 500 walkers, but throw away
        #the first 250 as a burn-in
        
        nsteps = 500
        for i,result in tqdm(enumerate(sampler.sample(pos,
                                                  iterations=nsteps)),
                             total=nsteps,
                             desc='Fitting '+gal_name):
            pos,probability,state = result
            
        pool.close()
            
        samples = sampler.chain[:, 250:, :].reshape((-1, ndim))
        
        # Save samples to dill pickle jar
        with open('samples/'+gal_name+'_samples.hkl', 'wb') as samples_dj:
            dill.dump(samples, samples_dj)
            
    if plot:
    
        #For error plotting later
        
        y_to_percentile_stars = []
        y_to_percentile_small = []
        y_to_percentile_large = []
        y_to_percentile_silicates = []
        y_to_percentile_total = []
        
        for isrf,\
            omega_star,\
            alpha,\
            y_sCM20,\
            y_lCM20,\
            y_aSilM5,\
            dust_scaling in samples[np.random.randint(len(samples), size=150)]:
                   
            small_grains,\
                large_grains,\
                silicates = read_sed(isrf,
                                     alpha)
            
            x,y = plt.plot(wavelength,omega_star*stars)[0].get_data()    
            y_to_percentile_stars.append(y)
            
            x,y = plt.plot(wavelength,y_sCM20*small_grains*dust_scaling)[0].get_data()    
            y_to_percentile_small.append(y)
            
            x,y = plt.plot(wavelength,y_lCM20*large_grains*dust_scaling)[0].get_data()    
            y_to_percentile_large.append(y)
            
            x,y = plt.plot(wavelength,y_aSilM5*silicates*dust_scaling)[0].get_data()    
            y_to_percentile_silicates.append(y)
            
            x,y = plt.plot(wavelength,dust_scaling*(y_sCM20*small_grains+\
                                        y_lCM20*large_grains+\
                                        y_aSilM5*silicates)+\
                                        omega_star*stars)[0].get_data()
            y_to_percentile_total.append(y)
            plt.close()
            
        y_upper_stars = np.percentile(y_to_percentile_stars,84,
                                      axis=0)
        y_lower_stars = np.percentile(y_to_percentile_stars,16,
                                      axis=0)
        y_upper_small = np.percentile(y_to_percentile_small,84,
                                      axis=0)
        y_lower_small = np.percentile(y_to_percentile_small,16,
                                      axis=0)
        y_upper_large = np.percentile(y_to_percentile_large,84,
                                      axis=0)
        y_lower_large = np.percentile(y_to_percentile_large,16,
                                      axis=0)
        y_upper_silicates = np.percentile(y_to_percentile_silicates,84,
                                      axis=0)
        y_lower_silicates = np.percentile(y_to_percentile_silicates,16,
                                      axis=0)
        y_upper = np.percentile(y_to_percentile_total,84,
                                axis=0)
        y_lower = np.percentile(y_to_percentile_total,16,
                                axis=0)
        
        #And calculate the median lines
        
        y_median_stars = np.percentile(y_to_percentile_stars,50,
                                       axis=0)
        y_median_small = np.percentile(y_to_percentile_small,50,
                                       axis=0)
        y_median_large = np.percentile(y_to_percentile_large,50,
                                       axis=0)
        y_median_silicates = np.percentile(y_to_percentile_silicates,50,
                                           axis=0)
        y_median_total = np.percentile(y_to_percentile_total,50,
                                       axis=0)
        
    #Calculate the percentiles
    
    percentiles =  zip(*np.percentile(samples, [16, 50, 84],axis=0))
     
    isrf,\
        omega_star,\
        alpha,\
        y_sCM20,\
        y_lCM20,\
        y_aSilM5,\
        dust_scaling = map(lambda percentiles: (percentiles[1],
                       percentiles[2]-percentiles[1],
                       percentiles[1]-percentiles[0]),
                       percentiles)
        
    if plot:
                
        #Calculate residuals
                   
        flux_model = filter_convolve(y_median_total)
        
        residuals = (obs_flux-flux_model)/obs_flux
        residual_err = obs_error/obs_flux
            
        residuals = np.array(residuals)*100
        residual_err = np.array(residual_err)*100
        
        #And residuals for the points not fitted
        
        flux_model_not_fit = filter_convolve_not_fit(y_median_total,
                                                     keys_not_fit)
        
        residuals_not_fit = (obs_flux_not_fit-flux_model_not_fit)/obs_flux_not_fit
        residual_err_not_fit = obs_error_not_fit/obs_flux_not_fit
            
        residuals_not_fit = np.array(residuals_not_fit)*100
        residual_err_not_fit = np.array(residual_err_not_fit)*100
        
        residual_upper = (y_upper-y_median_total)*100/y_median_total
        residual_lower = (y_lower-y_median_total)*100/y_median_total
        
        fig1 = plt.figure(figsize=(10,6))
        frame1 = fig1.add_axes((.1,.3,.8,.6))
        
        #Plot the best fit and errorbars. The flux errors here are only
        #RMS, so include overall calibration from Chris' paper
        
        for i in range(len(keys)):
            
            calib_uncert = {'Spitzer_3.6':0.03,
                            'Spitzer_4.5':0.03,
                            'Spitzer_5.8':0.03,
                            'Spitzer_8.0':0.03,
                            'Spitzer_24':0.05,
                            'Spitzer_70':0.1,
                            'Spitzer_160':0.12,
                            'WISE_3.4':0.029,
                            'WISE_4.6':0.034,     
                            'WISE_12':0.046,
                            'WISE_22':0.056,
                            'PACS_70':0.07,
                            'PACS_100':0.07,
                            'PACS_160':0.07,
                            'SPIRE_250':0.055,
                            'SPIRE_350':0.055,
                            'SPIRE_500':0.055,
                            'Planck_350':0.064,
                            'Planck_550':0.061,
                            'Planck_850':0.0078,
                            'SCUBA2_450':0.12,
                            'SCUBA2_850':0.08,
                            'IRAS_12':0.2,
                            'IRAS_25':0.2,
                            'IRAS_60':0.2,
                            'IRAS_100':0.2}[keys[i]]
            
            obs_error[i] += calib_uncert*obs_flux[i]
            
        for i in range(len(keys_not_fit)):
            
            calib_uncert = {'Spitzer_3.6':0.03,
                            'Spitzer_4.5':0.03,
                            'Spitzer_5.8':0.03,
                            'Spitzer_8.0':0.03,
                            'Spitzer_24':0.05,
                            'Spitzer_70':0.1,
                            'Spitzer_160':0.12,
                            'WISE_3.4':0.029,
                            'WISE_4.6':0.034,     
                            'WISE_12':0.046,
                            'WISE_22':0.056,
                            'PACS_70':0.07,
                            'PACS_100':0.07,
                            'PACS_160':0.07,
                            'SPIRE_250':0.055,
                            'SPIRE_350':0.055,
                            'SPIRE_500':0.055,
                            'Planck_350':0.064,
                            'Planck_550':0.061,
                            'Planck_850':0.0078,
                            'SCUBA2_450':0.12,
                            'SCUBA2_850':0.08,
                            'IRAS_12':0.2,
                            'IRAS_25':0.2,
                            'IRAS_60':0.2,
                            'IRAS_100':0.2}[keys_not_fit[i]]
            
            obs_error_not_fit[i] += calib_uncert*obs_flux_not_fit[i]
        
        #THEMIS models
        
        plt.fill_between(wavelength,y_lower_stars,y_upper_stars,
                         facecolor='m', interpolate=True,lw=0.5,
                         edgecolor='none', alpha=0.3)
        plt.fill_between(wavelength,y_lower_small,y_upper_small,
                         facecolor='b', interpolate=True,lw=0.5,
                         edgecolor='none', alpha=0.3)
        plt.fill_between(wavelength,y_lower_large,y_upper_large,
                         facecolor='g', interpolate=True,lw=0.5,
                         edgecolor='none', alpha=0.3)
        plt.fill_between(wavelength,y_lower_silicates,y_upper_silicates,
                         facecolor='r', interpolate=True,lw=0.5,
                         edgecolor='none', alpha=0.3)
        plt.fill_between(wavelength,y_lower,y_upper,
                         facecolor='k', interpolate=True,lw=0.5,
                         edgecolor='none', alpha=0.4)
        
        plt.plot(wavelength,y_median_stars,
                 c='m',
                 ls='--',
                 label='Stars')
        plt.plot(wavelength,y_median_small,
                 c='b',
                 ls='-.',
                 label='sCM20')
        plt.plot(wavelength,y_median_large,
                 c='g',
                 dashes=[2,2,2,2],
                 label='lCM20')
        plt.plot(wavelength,y_median_silicates,
                 c='r',
                 dashes=[5,2,10,2],
                 label='aSilM5')
        plt.plot(wavelength,y_median_total,
                 c='k',
                 label='Total')
        
        #Observed fluxes
        
        plt.errorbar(obs_wavelength,obs_flux,
                     yerr=obs_error,
                     c='k',
                     ls='none',
                     marker='.',
                     zorder=99)
        
        plt.errorbar(obs_wavelength_not_fit,
                     obs_flux_not_fit,
                     yerr=obs_error_not_fit,
                     c='r',
                     ls='none',
                     marker='.',
                     zorder=98)
        
        plt.xscale('log')
        plt.yscale('log')
        
        plt.xlim([1,1000])
        plt.ylim([0.5*10**np.floor(np.log10(np.min(obs_flux))-1),
                  10**np.ceil(np.log10(np.max(obs_flux))+1)])
        
        plt.legend(loc='upper left',
                   fontsize=14,
                   frameon=False)
        
        plt.ylabel(r'$F_\nu$ (Jy)',
                   fontsize=14)
        
        plt.yticks(fontsize=14)
        
        plt.tick_params(labelbottom=False)
        
        #Add in residuals
        
        frame2=fig1.add_axes((.1,.1,.8,.2))
        
        #Include the one-sigma errors in the residuals
        
        plt.fill_between(wavelength,residual_lower,residual_upper,
                         facecolor='k', interpolate=True,lw=0.5,
                         edgecolor='none', alpha=0.4)
        
        plt.errorbar(obs_wavelength,residuals,yerr=residual_err,c='k',marker='.',
                     ls='none',
                     zorder=99)
        plt.errorbar(obs_wavelength_not_fit,residuals_not_fit,
                     yerr=residual_err_not_fit,c='r',marker='.',
                     ls='none',
                     zorder=98)
        
        plt.axhline(0,ls='--',c='k')
        
        plt.xticks(fontsize=14)
        plt.yticks(fontsize=14)
        
        plt.xscale('log')
        
        plt.xlabel(r'$\lambda$ ($\mu$m)',
                   fontsize=14)
        plt.ylabel('Residual (%)',
                   fontsize=14)
        
        plt.xlim([1,1000])
        plt.ylim([-100,100])
        
        plt.savefig('plots/'+gal_name+'_sed.png',
                    bbox_inches='tight',
                    dpi=150)
        plt.savefig('plots/'+gal_name+'_sed.pdf',
                    bbox_inches='tight')
    
    #Corner plot -- convert the scaling factor to a hydrogen mass
    
    samples[:,-1] *= 1e-23
    samples[:,-1] *= (distance*1000*3.0857e18)**2
    samples[:,-1] *= 1.67e-27
    samples[:,-1] /= 2e30
    samples[:,-1] *= 4*np.pi
    
    mass_h = samples[:,-1].copy()
    
    #We now have a hydrogen mass in solar masses! Use the
    #relative abundances to turn this into a dust mass
    
    dgr_sCM20 = 0.17e-2
    dgr_lCM20 = 0.63e-3
    dgr_aSilM5 = 0.255e-2*2
    
    samples[:,-1] = samples[:,-1]*dgr_sCM20*samples[:,3] + \
                    samples[:,-1]*dgr_lCM20*samples[:,4] + \
                    samples[:,-1]*dgr_aSilM5*samples[:,5]
    
    samples[:,-1] = np.log10(samples[:,-1])
    
    #Because of varying grain sizes the abundances aren't really
    #physically meaningful. Turn into a dust mass for each component
    
    samples[:,3] = dgr_sCM20*mass_h*samples[:,3]
    samples[:,3] = np.log10(samples[:,3])
    samples[:,4] = dgr_lCM20*mass_h*samples[:,4]
    samples[:,4] = np.log10(samples[:,4])
    samples[:,5] = dgr_aSilM5*mass_h*samples[:,5]
    samples[:,5] = np.log10(samples[:,5])
    
    #Recalculate percentiles
    
    percentiles =  zip(*np.percentile(samples[:,3:], [16, 50, 84],axis=0))
     
    m_sCM20,\
        m_lCM20,\
        m_aSilM5,\
        m_dust = map(lambda percentiles: (percentiles[1],
                       percentiles[2]-percentiles[1],
                       percentiles[1]-percentiles[0]),
                       percentiles)
        
    if plot:
    
        corner.corner(samples, labels=[r'log$_{10}$ U',
                                       r'$\Omega_\ast$',
                                       r'$\alpha_\mathregular{sCM20}$',
                                       r'log$_{10}$ M$_\mathregular{sCM20}$',
                                       r'log$_{10}$ M$_\mathregular{lCM20}$',
                                       r'log$_{10}$ M$_\mathregular{aSilM5}$',
                                       r'log$_{10}$ M$_\mathregular{dust}$ (M$_\odot$)'],
                      quantiles=[0.16,0.84],
                      show_titles=True,
                      truths=[isrf[0],
                              omega_star[0],
                              alpha[0],
                              m_sCM20[0],
                              m_lCM20[0],
                              m_aSilM5[0],
                              m_dust[0]],
                      range=[0.995,0.995,0.995,0.995,0.995,0.995,0.995],
                      truth_color='k')
        
        plt.savefig('plots/'+gal_name+'_corner.png',
                    bbox_inches='tight',
                    dpi=150)
        plt.savefig('plots/'+gal_name+'_corner.pdf',
                    bbox_inches='tight')
    
    #Finally, write out code snippets for dustEM and SKIRT, if requested
    
    if dustem_output:
        
        with open('GRAIN_orig.DAT', 'r') as file :
            filedata = file.read()
            
            filedata = filedata.replace('[1.000000]','%.6f' % 10**isrf[0])
            filedata = filedata.replace('[0.170E-02]', '%.3E' % (0.17e-2*y_sCM20[0]))
            filedata = filedata.replace('[-5.00E-00]', '%.2E' % (alpha[0]))
            filedata = filedata.replace('[0.630E-03]', '%.3E' % (0.63e-3*y_lCM20[0]))
            filedata = filedata.replace('[0.255E-02]', '%.3E' % (0.255e-2*y_aSilM5[0]))
            
            # Write the converted file out
            with open('dustem_output/GRAIN_'+gal_name+'.dat', 'w') as file:
                file.write(filedata)
                
    if skirt_output:
        
        #Default, unchanging parameters
        
        #sCM20
        
        m_h = 1.6737236e-27
        amin = 0.0004e-6
        amax = 4.9e-6
        a_t = 0.e-6
        a_c = 0.05e-6
        a_u = 0.0001e-6
        gamma = 1
        zeta = 0
        eta = 0
        C = 1.717e-43
        rho_sCM20 = 1.6
        rho_sCM20 *= 100**3/1000
        
        a = np.linspace(amin,amax,100000)
        
        #lCM20
        
        a0_lCM20 = 0.007e-6
        rho_lCM20 = 1.57
        rho_lCM20 *= 100**3/1000
        
        #aSilM5
        
        a0_aSilM5 = 0.008e-6
        rho_aSilM5 = 2.19
        rho_aSilM5 *= 100**3/1000
        
        #Calculate new proportionality factors
                
        idx = np.where(a<=a_t)        
        f_ed = np.zeros(len(a))       
        f_ed = np.exp(-((a-a_t)/a_c)**gamma)        
        f_ed[idx] = 1        
        f_cv = (1+np.abs(zeta) * (a/a_u)**eta )**np.sign(zeta)       
        omega_a_sCM20 = a**-alpha[0] * f_ed * f_cv        
        m_d_n_h = 4/3*np.pi*rho_sCM20*np.trapz(a**3*omega_a_sCM20,a)
        
        prop_factor_sCM20 = y_sCM20[0]*0.17e-2/(m_d_n_h/m_h)
        
        
        omega_a_lCM20 = a**-1 * np.exp(-0.5*np.log(a/a0_lCM20)**2)        
        m_d_n_h = 4/3*np.pi*rho_lCM20*np.trapz(a**3*omega_a_lCM20,a)
        
        prop_factor_lCM20 = y_lCM20[0]*0.63e-3/(m_d_n_h/m_h)
        
        
        omega_a_aSilM5 = a**-1 * np.exp(-0.5*np.log(a/a0_aSilM5)**2)
        m_d_n_h = 4/3*np.pi*rho_aSilM5*np.trapz(a**3*omega_a_aSilM5,a)

        prop_factor_aSilM5 = y_aSilM5[0]*0.255e-2/(m_d_n_h/m_h)
        
        #Write these new values out
        
        with open('template.ski', 'r') as file :
            filedata = file.read()
            
            filedata = filedata.replace('[alpha]','-%.1f' % (alpha[0]))
            filedata = filedata.replace('[y_sCM20]','%.11e' % (prop_factor_sCM20))
            filedata = filedata.replace('[y_lCM20]','%.11e' % (prop_factor_lCM20))
            filedata = filedata.replace('[y_aSilM5]','%.11e' % (prop_factor_aSilM5))
            
            # Write the converted file out
            with open('skirt_output/template_'+gal_name+'.ski', 'w') as file:
                file.write(filedata)

print('Code complete, took %.2fm' % ( (time.time() - start_time)/60 ))