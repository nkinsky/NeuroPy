from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scipy.signal as sg
import scipy.stats as stats
from scipy import fftpack
import mathutil
import signal_process
from parsePath import Recinfo
from joblib import Parallel, delayed
from behavior import behavior_epochs
from artifactDetect import findartifact


class Hswa:
    """Analyses related to hippocampal slow oscillations

    Attributes
    ----------

    Methods
    ----------
    detect :
        detects putative events in the entire recording

    """

    def __init__(self, basepath):

        if isinstance(basepath, Recinfo):
            self._obj = basepath
        else:
            self._obj = Recinfo(basepath)

        # ------- defining file names ---------
        filePrefix = self._obj.files.filePrefix

        @dataclass
        class files:
            events: Path = filePrefix.with_suffix(".hswa.npy")

        self.files = files()
        self._load()

    def _load(self):

        if (f := self.files.events).is_file():
            evt = np.load(f, allow_pickle=True).item()
            self.events: pd.DataFrame = evt["events"]
            self.params = evt["DetectionParams"]

    def detect(self, chan, freq_band=(0.5, 4)):
        """Caculate delta events

        chan --> filter delta --> identify peaks and troughs within sws epochs only --> identifies a slow wave as trough to peak --> thresholds for 100ms minimum duration

        Parameters
        ----------
        chan : int
            channel to be used for detection
        freq_band : tuple, optional
            frequency band in Hz, by default (0.5, 4)
        """

        lfpsRate = self._obj.lfpSrate
        deltachan = self._obj.geteeg(chans=chan)

        # ---- filtering best ripple channel in delta band
        t = np.linspace(0, len(deltachan) / lfpsRate, len(deltachan))
        lf, hf = freq_band
        delta_sig = signal_process.filter_sig.bandpass(deltachan, lf=lf, hf=hf)
        delta = stats.zscore(delta_sig)  # normalization w.r.t session
        delta = -delta  # flipping as this is in sync with cortical slow wave

        # ---- finding peaks and trough for delta oscillations

        up = sg.find_peaks(delta)[0]
        down = sg.find_peaks(-delta)[0]

        if up[0] < down[0]:
            up = up[1:]
        if up[-1] > down[-1]:
            up = up[:-1]

        sigdelta = []
        for i in range(len(down) - 1):
            tbeg = t[down[i]]
            tpeak = t[up[i]]
            tend = t[down[i + 1]]
            peakamp = delta[up[i]]
            endamp = delta[down[i + 1]]
            # ------ thresholds for selecting delta --------
            # if (peakamp > 2 and endamp < 0) or (peakamp > 1 and endamp < -1.5):
            sigdelta.append([peakamp, endamp, tpeak, tbeg, tend])

        sigdelta = np.asarray(sigdelta)
        print(f"{len(sigdelta)} delta detected")

        data = pd.DataFrame(
            {
                "start": sigdelta[:, 3],
                "end": sigdelta[:, 4],
                "peaktime": sigdelta[:, 2],
                "peakamp": sigdelta[:, 0],
                "endamp": sigdelta[:, 1],
            }
        )
        detection_params = {"freq_band": freq_band, "chan": chan}
        hipp_slow_wave = {"events": data, "DetectionParams": detection_params}

        np.save(self.files.events, hipp_slow_wave)
        self._load()

    def plot(self):
        """Gives a comprehensive view of the detection process with some statistics and examples"""
        eegSrate = self._obj.lfpSrate
        deltachan = self.params["chan"]
        goodchangrp = self._obj.goodchangrp
        chosenShank = [_ for _ in goodchangrp if deltachan in _]
        times = self.events.peaktime.to_numpy()
        tbeg = self.events.start.to_numpy()
        tend = self.events.end.to_numpy()

        eegdata = self._obj.geteeg(chans=chosenShank)
        # sort_ind = np.argsort(peakpower)
        # peakpower = peakpower[sort_ind]
        # times = times[sort_ind, :]
        # rpl_duration = np.diff(times, axis=1) * 1000  # in ms
        frames = times * eegSrate
        framesbeg = tbeg * eegSrate
        framesend = tend * eegSrate
        ndelta = len(times)

        fig = plt.figure(1, figsize=(6, 10))
        gs = gridspec.GridSpec(2, 10, figure=fig)
        fig.subplots_adjust(hspace=0.2)

        delta_to_plot = list(range(50, 60))

        beg_eeg = int(framesbeg[delta_to_plot[0]]) - eegSrate
        end_eeg = int(framesend[delta_to_plot[-1]]) + eegSrate
        lfp = stats.zscore(eegdata[beg_eeg:end_eeg, :])
        lfp = lfp + np.linspace(40, 0, lfp.shape[1])
        eegt = np.linspace(beg_eeg, end_eeg, len(lfp))
        ax1 = fig.add_subplot(gs[0, :])
        ax1.plot(eegt, lfp, "#444040", linewidth=0.8)
        ax1.set_title("Raw lfp", loc="left")

        for ind, delta in enumerate(delta_to_plot):
            start = int(framesbeg[delta])
            peak = int(frames[delta])
            end = int(framesend[delta])
            ax1.plot([peak, peak], [-8, 47], "--")
            ax1.fill_between([start, end], [-6, -6], [45, 45], alpha=0.3)
            ax1.axis("off")

        deltabandlfp = signal_process.filter_sig.delta(lfp, ax=0)
        deltabandlfp = deltabandlfp + np.linspace(40, 0, lfp.shape[1])
        ax2 = fig.add_subplot(gs[1, :])
        ax2.plot(eegt, deltabandlfp, "#444040", linewidth=0.8)
        ax2.set_title("Filtered lfp", loc="left")
        for ind, delta in enumerate(delta_to_plot):
            start = int(framesbeg[delta])
            peak = int(frames[delta])
            end = int(framesend[delta])
            ax2.plot([peak, peak], [-8, 47], "--")
            ax2.fill_between([start, end], [-6, -6], [45, 45], alpha=0.3)
            ax2.axis("off")

        subname = self._obj.session.subname
        fig.suptitle(f"Delta wave detection of {subname}")


class Ripple:
    def __init__(self, basepath):

        if isinstance(basepath, Recinfo):
            self._obj = basepath
        else:
            self._obj = Recinfo(basepath)

        # ------- defining file names ---------
        filePrefix = self._obj.files.filePrefix

        @dataclass
        class files:
            ripples: Path = filePrefix.with_suffix(".ripples.npy")
            bestRippleChans: Path = filePrefix.with_suffix(".BestRippleChans.npy")
            neuroscope: Path = filePrefix.with_suffix(".evt.rpl")

        self.files = files()
        self._load()

    def _load(self):
        if (f := self.files.ripples).is_file():

            ripple_evt = np.load(f, allow_pickle=True).item()
            self.events: pd.DataFrame = ripple_evt["events"]
            self.params = ripple_evt["DetectionParams"]

        if (f := self.files.bestRippleChans).is_file():
            data = np.load(f, allow_pickle=True).item()
            self.bestchans = data["channels"]

    def channels(self, viewselection=1):
        """Channels which represent high ripple power in each shank"""
        duration = 1 * 60 * 60  # 1 hour chunk of lfp in seconds
        nShanks = self._obj.nShanks

        lfpCA1 = self._obj.geteeg(chans=self._obj.goodchans, timeRange=[0, duration])
        goodChans = self._obj.goodchans  # keeps order

        # --- filter and hilbert amplitude for each channel --------
        avgRipple = np.zeros(len(lfpCA1))
        for i, lfp in enumerate(lfpCA1):
            rippleband = signal_process.filter_sig.ripple(lfp)
            amplitude_envelope = np.abs(signal_process.hilbertfast(rippleband))
            avgRipple[i] = np.mean(amplitude_envelope, axis=0)

        rippleamp_chan = dict(zip(goodChans, avgRipple))

        rplchan_shank, metricAmp = [], []
        for shank in range(nShanks):
            goodChans_shank = np.asarray(self._obj.goodchangrp[shank])

            if goodChans_shank.size != 0:
                avgrpl_shank = np.asarray(
                    [rippleamp_chan[chan] for chan in goodChans_shank]
                )
                chan_max = goodChans_shank[np.argmax(avgrpl_shank)]
                rplchan_shank.append(chan_max)
                metricAmp.append(np.max(avgrpl_shank))

        rplchan_shank = np.asarray(rplchan_shank)
        metricAmp = np.asarray(metricAmp)
        sort_chan = np.argsort(metricAmp)
        # --- the reason metricAmp was used to allow using other metrics such as median
        bestripplechans = {
            "channels": rplchan_shank[sort_chan],
            "metricAmp": metricAmp[sort_chan],
        }

        filename = self.files.bestRippleChans
        np.save(filename, bestripplechans)
        self._load()  # load variables immediately into existence

    def detect(
        self,
        lowFreq=150,
        highFreq=240,
        chans=None,
        lowthreshold=1,
        highthreshold=5,
        minDuration=0.05,
        maxDuration=0.450,
        mergeDistance=0.05,
        # maxPeakPower=60,
    ):
        """[summary]

        Parameters
        ----------
        lowFreq : int, optional
            [description], by default 150
        highFreq : int, optional
            [description], by default 240
        chans : list
            channels used for ripple detection, if None then chooses best chans
        """
        # TODO chnage raw amplitude threshold to something statistical
        SampFreq = self._obj.lfpSrate

        if chans is None:
            bestchans = self.bestchans
        else:
            bestchans = chans

        eeg = self._obj.geteeg(chans=bestchans)
        zscsignal = []
        sharpWv_sig = np.zeros(eeg[0].shape[-1])
        for lfp in eeg:
            yf = signal_process.filter_sig.bandpass(lfp, lf=lowFreq, hf=highFreq)
            zsc_chan = stats.zscore(np.abs(signal_process.hilbertfast(yf)))
            zscsignal.append(zsc_chan)

            broadband = signal_process.filter_sig.bandpass(lfp, lf=2, hf=50)
            sharpWv_sig += stats.zscore(np.abs(signal_process.hilbertfast(broadband)))
        zscsignal = np.asarray(zscsignal)

        # ---------setting noisy period zero --------
        artifact = findartifact(self._obj)
        if artifact.time is not None:
            noisy_frames = artifact.getframes()
            zscsignal[:, noisy_frames] = 0

        # ------hilbert transform --> binarize by > than lowthreshold
        maxPower = np.max(zscsignal, axis=0)
        ThreshSignal = np.where(zscsignal > lowthreshold, 1, 0).sum(axis=0)
        ThreshSignal = np.diff(np.where(ThreshSignal > 0, 1, 0))
        start_ripple = np.where(ThreshSignal == 1)[0]
        stop_ripple = np.where(ThreshSignal == -1)[0]

        # --- getting rid of incomplete ripples at begining or end ---------
        if start_ripple[0] > stop_ripple[0]:
            stop_ripple = stop_ripple[1:]
        if start_ripple[-1] > stop_ripple[-1]:
            start_ripple = start_ripple[:-1]

        firstPass = np.vstack((start_ripple, stop_ripple)).T
        print(f"{len(firstPass)} ripples detected initially")

        # --------merging close ripples------------
        minInterRippleSamples = mergeDistance * SampFreq
        secondPass = []
        ripple = firstPass[0]
        for i in range(1, len(firstPass)):
            if firstPass[i, 0] - ripple[1] < minInterRippleSamples:
                ripple = [ripple[0], firstPass[i, 1]]
            else:
                secondPass.append(ripple)
                ripple = firstPass[i]

        secondPass.append(ripple)
        secondPass = np.asarray(secondPass)
        print(f"{len(secondPass)} ripples reamining after merging")

        # ------delete ripples with less than threshold power--------
        thirdPass = []
        peakNormalizedPower, peaktime, peakSharpWave = [], [], []

        for i in range(0, len(secondPass)):
            maxValue = max(maxPower[secondPass[i, 0] : secondPass[i, 1]])
            if maxValue > highthreshold:
                thirdPass.append(secondPass[i])
                peakNormalizedPower.append(maxValue)
                peaktime.append(
                    secondPass[i, 0]
                    + np.argmax(maxPower[secondPass[i, 0] : secondPass[i, 1]])
                )
                peakSharpWave.append(
                    secondPass[i, 0]
                    + np.argmax(sharpWv_sig[secondPass[i, 0] : secondPass[i, 1]])
                )
        thirdPass = np.asarray(thirdPass)
        print(f"{len(thirdPass)} ripples reamining after deleting weak ripples")
        print(thirdPass.shape)

        ripple_duration = np.diff(thirdPass, axis=1) / SampFreq
        ripples = pd.DataFrame(
            {
                "start": thirdPass[:, 0],
                "end": thirdPass[:, 1],
                "peakNormalizedPower": peakNormalizedPower,
                "peakSharpWave": np.asarray(peakSharpWave),
                "peaktime": np.asarray(peaktime),
                "duration": ripple_duration.squeeze(),
            }
        )

        # ---------delete very short ripples--------
        ripples = ripples[ripples.duration >= minDuration]
        print(f"{len(ripples)} ripples reamining after deleting short ripples")

        # ----- delete ripples with unrealistic high power
        # artifactRipples = np.where(peakNormalizedPower > maxPeakPower)[0]
        # fourthPass = np.delete(thirdPass, artifactRipples, 0)
        # peakNormalizedPower = np.delete(peakNormalizedPower, artifactRipples)

        # ---------delete very long ripples---------
        ripples = ripples[ripples.duration <= maxDuration]
        print(f"{len(ripples)} ripples reamining after deleting very long ripples")

        # ----- converting to all time stamps to seconds --------
        ripples[["start", "end", "peakSharpWave", "peaktime"]] /= SampFreq  # seconds

        now = datetime.now()
        dt_string = now.strftime("%d/%m/%Y %H:%M:%S")

        ripples = {
            "events": ripples.reset_index(drop=True),
            "Info": {"Date": dt_string},
            "DetectionParams": {
                "lowThres": lowthreshold,
                "highThresh": highthreshold,
                # "ArtifactThresh": maxPeakPower,
                "lowFreq": lowFreq,
                "highFreq": highFreq,
                "minDuration": minDuration,
                "maxDuration": maxDuration,
                "mergeDistance": mergeDistance,
            },
        }

        np.save(self.files.ripples, ripples)
        print(f"{self.files.ripples} created")
        self._load()

    def export2Neuroscope(self):
        with self.files.neuroscope.open("w") as a:
            for event in self.events.itertuples():
                a.write(
                    f"{event.start*1000} start\n{event.peakSharpWave*1000} peakSW\n{event.end*1000} end\n"
                )

    def plot_summary(self, random=False, shank_id=None):
        """Plots 10 of detected ripples across two randomly selected shanks with their filtered lfp

        Parameters
        ----------
        random : bool, optional
            if True then randomly plots 10 ripples, by default False then it plots 5 weakest and 5 strongest ripples
        """
        fig = plt.figure(num=None, figsize=(10, 6))
        gs = gridspec.GridSpec(2, 10, figure=fig)
        fig.subplots_adjust(hspace=0.5)

        changrp = [shank for shank in self._obj.goodchangrp if shank]
        channels = np.concatenate(np.random.choice(changrp, 2))  # random 2 shanks
        ripples = self.events
        peakpower = self.events.peakNormalizedPower.values
        params = self.params

        # --- sorting ripples by peakpower ------
        sort_ind = np.argsort(peakpower)

        # ---- selecting few ripples to plot -----------
        if random:
            ripple_to_plot = np.random.choice(sort_ind, 10)
        else:
            ripple_to_plot = np.concatenate((sort_ind[:5], sort_ind[-5:]))

        # ------ plotting ripples and filtered lfp -----------
        for ind, ripple in enumerate(ripple_to_plot):

            ax = fig.add_subplot(gs[1, ind])
            self.plot_example(ax=ax, ripple_indx=ripple, pad=0.3, shank_id=shank_id)
            ax.set_title(
                f"zsc = {round(peakpower[ripple],2)} \n {round(ripples.loc[ripple].duration*1000)} ms",
                loc="left",
            )
            ax.axis("off")

        # ------ plotting parameters used during detection ----------
        ax = fig.add_subplot(gs[0, 0])
        ax.text(
            0,
            0.8,
            f" highThresh ={params['highThresh']}\n lowThresh ={params['lowThres']}\n minDuration = {params['minDuration']}\n maxDuration = {params['maxDuration']} \n mergeRipple = {params['mergeDistance']} \n #Ripples = {len(peakpower)}",
        )
        ax.axis("off")

        # ----- plotting channels used for detection --------
        ax = fig.add_subplot(gs[0, 1:4])
        try:
            self._obj.probemap.plot(self.bestchans, ax=ax)
            ax.set_title("selected channel")
        except AttributeError:
            print(
                "No probemap provided - provide to visualize ripple channel location!"
            )

        # ---- peaknormalized power distribution plot ---------
        ax = fig.add_subplot(gs[0, 5])
        histpower, edgespower = np.histogram(peakpower, bins=100)
        ax.plot(edgespower[:-1], histpower, color="#544a4a")
        ax.set_xlabel("Zscore value")
        ax.set_ylabel("Counts")
        ax.set_yscale("log")

        # ----- distribution of ripple duration ---------
        ax = fig.add_subplot(gs[0, 6])
        histdur, edgesdur = np.histogram(ripples.duration * 1000, bins=100)
        ax.plot(edgesdur[:-1], histdur, color="#544a4a")
        ax.set_xlabel("Duration (ms)")
        # ax.set_ylabel("Counts")
        ax.set_yscale("log")

        subname = self._obj.session.subname
        fig.suptitle(f"Ripple detection of {subname}")

    def plot_example(
        self, ax=None, ripple_indx=None, shank_id=None, pad=0.2, color="k"
    ):
        changrp = self._obj.channelgroups
        nShanks = self._obj.nShanks
        if ripple_indx is None:
            ripple_indx = np.random.randint(low=0, high=len(self.events))
        if shank_id is None:
            shank_id = np.random.randint(low=0, high=nShanks)

        ripple_time = self.events.loc[ripple_indx][["start", "end"]].to_list()
        lfp = np.array(self._obj.geteeg(chans=changrp[shank_id], timeRange=ripple_time))
        lfp = lfp / np.max(lfp)  # scaling
        lfp = lfp - lfp[:, 0][:, np.newaxis]  # np.min(lfp, axis=1, keepdims=True)
        pad_vals = np.linspace(0, len(lfp) * pad, len(lfp))[::-1]
        lfp = lfp + pad_vals[:, np.newaxis]

        if ax is None:
            _, ax = plt.subplots(1, 1)

        print(f"Plotting ripple no. {ripple_indx}")
        ax.clear()
        ax.plot(lfp.T, color=color)
        ax.set_yticks(pad_vals)
        ax.set_yticklabels(changrp[shank_id])
        ax.set_xticklabels([])
        ax.spines["left"].set_visible(False)
        ax.spines["bottom"].set_visible(False)
        ax.tick_params(axis="both", length=0)

        return ax

    def plot_ripples(self, period, ax):
        """Plot ripples between this period on a given axis

        Parameters
        ----------
        period : list
            list of length 2, in seconds
        ax : axis object
            axis
        """

        events = self.events[
            (self.events.start > period[0]) & (self.events.start < period[1])
        ]

        for epoch in events.itertuples():
            color = "#ff928a"
            ax.axvspan(epoch.start, epoch.end, facecolor=color, alpha=0.7)


class Spindle:
    lowthresholdFactor = 1.5
    highthresholdFactor = 4
    minSpindleDuration = 350
    mergeDistance = 125

    def __init__(self, basepath):

        if isinstance(basepath, Recinfo):
            self._obj = basepath
        else:
            self._obj = Recinfo(basepath)

        # ------- defining file names ---------
        filePrefix = self._obj.files.filePrefix

        @dataclass
        class files:
            events: Path = filePrefix.with_suffix(".spindles.npy")
            bestChan: Path = filePrefix.with_suffix(".BestSpindleChan.npy")
            neuroscope: Path = filePrefix.with_suffix(".evt.spn")

        self.files = files()
        self._load()

    def _load(self):
        if (f := self.files.events).is_file():
            spindle_evt = np.load(f, allow_pickle=True).item()
            self.time = spindle_evt["times"]
            self.peakpower = spindle_evt["peakPower"]
            self.peaktime = spindle_evt["peaktime"]

    def best_chan_lfp(self):
        """Returns just best of best channels of each shank or returns all best channels of shanks

        Returns:
            [type] -- [description]
        """
        lfpsrate = self._obj.lfpSrate

        lfpinfo = np.load(self._obj.files.spindlelfp, allow_pickle=True).item()
        chan = np.asarray(lfpinfo["channel"])
        lfp = np.asarray(lfpinfo["lfp"])
        coords = lfpinfo["coords"]

        return lfp, chan, coords

    def channels(self, viewselection=1):
        """Channel which represent high spindle power during nrem across all channels"""
        sampleRate = self._obj.recinfo.lfpSrate
        duration = 1 * 60 * 60  # chunk of lfp in seconds
        nyq = 0.5 * sampleRate  # Nyquist frequency
        nChans = self._obj.nChans
        badchans = self._obj.badchans
        allchans = self._obj.channels
        changrp = self._obj.channelgroups
        nShanks = self._obj.nShanks
        probemap = self._obj.probemap()
        brainChannels = [item for sublist in changrp[:nShanks] for item in sublist]
        dict_probemap = dict(zip(brainChannels, zip(probemap[0], probemap[1])))

        states = self._obj.brainstates.states
        states = states.loc[states["name"] == "nrem", ["start", "end"]]
        nremframes = (np.asarray(states.values.tolist()) * sampleRate).astype(int)
        reqframes = []
        for (start, end) in nremframes:
            reqframes.extend(np.arange(start, end))

        reqframes = np.asarray(reqframes)

        fileName = self._obj.sessinfo.recfiles.eegfile
        lfpAll = np.memmap(fileName, dtype="int16", mode="r")
        lfpAll = np.memmap.reshape(lfpAll, (int(len(lfpAll) / nChans), nChans))
        lfpCA1 = lfpAll[reqframes, :]

        # exclude badchannels
        lfpCA1 = np.delete(lfpCA1, badchans, 1)
        goodChans = np.setdiff1d(allchans, badchans, assume_unique=True)  # keeps order

        # filter and hilbet amplitude for each channel
        hilbertfast = lambda x: sg.hilbert(x, fftpack.next_fast_len(len(x)))[: len(x)]
        avgSpindle = np.zeros(lfpCA1.shape[1])
        for i in range(lfpCA1.shape[1]):
            spindleband = signal_process.filter_sig.spindle(lfpCA1[:, i])
            amplitude_envelope = np.abs(hilbertfast(spindleband))
            avgSpindle[i] = np.mean(amplitude_envelope)

        spindleamp_chan = dict(zip(goodChans, avgSpindle))

        # plt.plot(probemap[0], probemap[1], ".", color="#bfc0c0")
        bestchan = goodChans[np.argmax(avgSpindle)]
        lfp = lfpAll[:, np.argmax(avgSpindle)]
        coords = dict_probemap[bestchan]

        # the reason metricAmp name was used to allow using other metrics such median
        bestspindlechan = dict(
            zip(
                ["channel", "lfp", "coords"],
                [bestchan, lfp, coords],
            )
        )

        filename = self._obj.sessinfo.files.spindlelfp
        np.save(filename, bestspindlechan)

    def detect(self):
        """ripples lfp nchans x time

        Returns:
            [type] -- [description]
        """
        sampleRate = self._obj.recinfo.lfpSrate
        lowFreq = 9
        highFreq = 18

        spindlelfp, _, _ = self.best_chan_lfp()
        signal = np.asarray(spindlelfp, dtype=np.float)

        yf = signal_process.filter_sig.bandpass(signal, lf=8, hf=16, ax=-1)
        hilbertfast = lambda x: sg.hilbert(x, fftpack.next_fast_len(len(x)))[: len(x)]
        amplitude_envelope = np.abs(hilbertfast(yf))
        zscsignal = stats.zscore(amplitude_envelope, axis=-1)

        # delete ripples in noisy period
        deadfile = (self._obj.sessinfo.files.filePrefix).with_suffix(".dead")
        if deadfile.is_file():
            with deadfile.open("r") as f:
                noisy = []
                for line in f:
                    epc = line.split(" ")
                    epc = [float(_) for _ in epc]
                    noisy.append(epc)
                noisy = np.asarray(noisy)
                noisy = ((noisy / 1000) * sampleRate).astype(int)

            for noisy_ind in range(noisy.shape[0]):
                st = noisy[noisy_ind, 0]
                en = noisy[noisy_ind, 1]
                numnoisy = en - st
                zscsignal[st:en] = np.zeros((numnoisy))

        # hilbert transform --> binarize by > than lowthreshold
        ThreshSignal = np.diff(np.where(zscsignal > self.lowthresholdFactor, 1, 0))
        start_spindle = np.where(ThreshSignal == 1)[0]
        stop_spindle = np.where(ThreshSignal == -1)[0]

        if start_spindle[0] > stop_spindle[0]:
            stop_spindle = stop_spindle[1:]
        if start_spindle[-1] > stop_spindle[-1]:
            start_spindle = start_spindle[:-1]

        firstPass = np.vstack((start_spindle, stop_spindle)).T
        print(f"{len(firstPass)} spindles detected initially")

        # ===== merging close spindles =========
        minInterspindleSamples = self.mergeDistance / 1000 * sampleRate
        secondPass = []
        spindle = firstPass[0]
        for i in range(1, len(firstPass)):
            if firstPass[i, 0] - spindle[1] < minInterspindleSamples:
                # Merging spindles
                spindle = [spindle[0], firstPass[i, 1]]
            else:
                secondPass.append(spindle)
                spindle = firstPass[i]
        secondPass.append(spindle)
        secondPass = np.asarray(secondPass)
        print(f"{len(secondPass)} spindles remaining after merging")

        # =======delete spindles with less than threshold power
        thirdPass = []
        peakNormalizedPower, peaktime = [], []
        for i in range(0, len(secondPass)):
            maxValue = max(zscsignal[secondPass[i, 0] : secondPass[i, 1]])
            if maxValue >= self.highthresholdFactor:
                thirdPass.append(secondPass[i])
                peakNormalizedPower.append(maxValue)
                peaktime.append(
                    [
                        secondPass[i, 0]
                        + np.argmax(zscsignal[secondPass[i, 0] : secondPass[i, 1]])
                    ]
                )

        thirdPass = np.asarray(thirdPass)
        spindle_duration = np.diff(thirdPass, axis=1) / sampleRate * 1000
        print(f"{len(thirdPass)} spindles remaining after deleting weak spindles")

        # delete very short spindles
        shortspindles = np.where(spindle_duration < self.minSpindleDuration)[0]
        fourthPass = np.delete(thirdPass, shortspindles, 0)
        peakNormalizedPower = np.delete(peakNormalizedPower, shortspindles)
        spindle_duration = np.delete(spindle_duration, shortspindles)
        peaktime = np.delete(peaktime, shortspindles)
        print(f"{len(fourthPass)} spindles remaining after deleting short spindles")

        # delete spindles in non-nrem periods
        states = self._obj.brainstates.states
        states = states.loc[states["name"] == "nrem", ["start", "end"]]
        nremframes = (np.asarray(states.values.tolist()) * sampleRate).astype(int)
        reqframes = []
        for (start, end) in nremframes:
            reqframes.extend(np.arange(start, end))
        reqframes = np.asarray(reqframes)

        outside_spindles = []
        for ind, (start, _) in enumerate(fourthPass):
            if start not in reqframes:
                outside_spindles.extend([ind])
        outside_spindles = np.asarray(outside_spindles)

        fifthPass = np.delete(fourthPass, outside_spindles, 0)
        peakNormalizedPower = np.delete(peakNormalizedPower, outside_spindles)
        spindle_duration = np.delete(spindle_duration, outside_spindles)
        peaktime = np.delete(peaktime, outside_spindles)

        print(f"{len(fifthPass)} spindles finally kept after excluding outside nrem")

        now = datetime.now()
        dt_string = now.strftime("%d/%m/%Y %H:%M:%S")

        spindles = dict()
        spindles["times"] = fifthPass / sampleRate
        spindles["peakPower"] = peakNormalizedPower
        spindles["peaktime"] = peaktime / sampleRate
        spindles["DetectionParams"] = {
            "lowThres": self.lowthresholdFactor,
            "highThresh": self.highthresholdFactor,
            "lowFreq": lowFreq,
            "highFreq": highFreq,
            "minDuration": self.minSpindleDuration,
        }
        spindles["Info"] = {"Date": dt_string}

        # return spindles

        np.save(self._obj.sessinfo.files.spindle_evt, spindles)
        print(f"{self._obj.sessinfo.files.spindle_evt.name} created")

    def plot(self):
        """Gives a comprehensive view of the detection process with some statistics and examples"""
        _, spindlechan, coord = self.best_chan_lfp()
        eegSrate = self._obj.lfpSrate
        probemap = self._obj.probemap()
        nChans = self._obj.nChans
        changrp = self._obj.channelgroups
        chosenShank = changrp[1] + changrp[2]
        times = self.time
        peakpower = self.peakpower
        eegfile = self._obj.recfiles.eegfile
        eegdata = np.memmap(eegfile, dtype="int16", mode="r")
        eegdata = np.memmap.reshape(eegdata, (int(len(eegdata) / nChans), nChans))
        eegdata = eegdata[:, chosenShank]

        sort_ind = np.argsort(peakpower)
        peakpower = peakpower[sort_ind]
        times = times[sort_ind, :]
        rpl_duration = np.diff(times, axis=1) * 1000  # in ms
        frames = times * eegSrate
        nspindles = len(peakpower)

        fig = plt.figure(1, figsize=(6, 10))
        gs = gridspec.GridSpec(3, 10, figure=fig)
        fig.subplots_adjust(hspace=0.5)

        spindles_to_plot = list(range(5)) + list(range(nspindles - 5, nspindles))
        for ind, spindle in enumerate(spindles_to_plot):
            print(spindle)
            start = int(frames[spindle, 0])
            end = int(frames[spindle, 1])
            lfp = stats.zscore(eegdata[start:end, :])
            ripplebandlfp = signal_process.filter_sig.spindle(lfp, ax=0)
            # lfp = (lfp.T - np.median(lfp, axis=1)).T
            lfp = lfp + np.linspace(40, 0, lfp.shape[1])
            ripplebandlfp = ripplebandlfp + np.linspace(40, 0, lfp.shape[1])
            duration = (lfp.shape[0] / eegSrate) * 1000  # in ms

            ax = fig.add_subplot(gs[1, ind])
            ax.plot(lfp, "#fa761e", linewidth=0.8)
            ax.set_title(
                f"zsc = {round(peakpower[spindle],2)}, {round(duration)} ms", loc="left"
            )
            # ax.set_xlim([0, self.maxSpindleDuration / 1000 * eegSrate])
            ax.axis("off")

            ax = fig.add_subplot(gs[2, ind])
            ax.plot(ripplebandlfp, linewidth=0.8, color="#594f4f")
            # ax.set_title(f"{round(peakpower[ripple],2)}")
            # ax.set_xlim([0, self.maxSpindleDuration / 1000 * eegSrate])
            ax.axis("off")

        ax = fig.add_subplot(gs[0, 0])
        ax.text(
            0,
            0.8,
            f" highThresh ={self.highthresholdFactor}\n lowThresh ={self.lowthresholdFactor}\n minDuration = {self.minSpindleDuration}\n mergeSpindle = {self.mergeDistance} \n #Spindles = {len(peakpower)}",
        )
        ax.axis("off")

        ax = fig.add_subplot(gs[0, 1:4])
        coord = np.asarray(coord)
        ax.plot(probemap[0], probemap[1], ".", color="#cdc6c6")
        ax.plot(coord[0], coord[1], "r.")
        ax.axis("off")
        ax.set_title("selected channel")

        ax = fig.add_subplot(gs[0, 5])
        histpower, edgespower = np.histogram(peakpower, bins=100)
        ax.plot(edgespower[:-1], histpower, color="#544a4a")
        ax.set_xlabel("Zscore value")
        ax.set_ylabel("Counts")
        # ax.set_yscale("log")

        ax = fig.add_subplot(gs[0, 6])
        histdur, edgesdur = np.histogram(rpl_duration, bins=100)
        ax.plot(edgesdur[:-1], histdur, color="#544a4a")
        ax.set_xlabel("Duration (ms)")
        # ax.set_ylabel("Counts")
        # ax.set_yscale("log")

        subname = self._obj.sessinfo.session.subname
        fig.suptitle(f"Spindle detection of {subname}")

    def export2Neuroscope(self):
        times = self.time * 1000  # convert to ms
        file_neuroscope = self._obj.sessinfo.files.filePrefix.with_suffix(".evt.spn")
        with file_neuroscope.open("w") as a:
            for beg, stop in times:
                a.write(f"{beg} start\n{stop} end\n")


class Theta:
    """Everything related to theta oscillations

    Parameters
    -----------
    basepath : str or Recinfo()
        path of the data folder or instance of Recinfo()

    Attributes
    -----------
    bestchan : int
        channel with highest area under the curve for frequency range 5-20 Hz
    chansOrder : array
        channels in decreasing order of theta power during MAZE exploration

    Methods
    -----------
    getBestChanlfp()
        Returns lfp/eeg of the channel with highest auc
    detectBestChan()
        Calculates AUC under theta band (5-20 Hz) for all channels and sorts it
    """

    def __init__(self, basepath):

        if isinstance(basepath, Recinfo):
            self._obj = basepath
        else:
            self._obj = Recinfo(basepath)

        # ------- defining file names ---------
        filePrefix = self._obj.files.filePrefix

        @dataclass
        class files:
            bestThetachan: str = filePrefix.with_suffix(".bestThetaChan.npy")

        self.files = files()
        self._load()

    def _load(self):
        if (f := self.files.bestThetachan).is_file():
            data = np.load(f, allow_pickle=True).item()
            self.bestchan = data["chanorder"][0]
            self.chansOrder = data["chanorder"]

    def getBestChanlfp(self):
        return self._obj.geteeg(chans=self.bestchan)

    def _getAUC(self, eeg):
        """Calculates area under the curve for frequency range 5-20 Hz

        Parameters
        ----------
        eeg : [array]
            channels x time, has to be two dimensional

        Returns
        -------
        [type]
            [description]
        """
        eegSrate = self._obj.lfpSrate

        assert isinstance(eeg, list), "list of lfps needs"
        assert len(eeg) > 1, "More than one channel needed"

        aucChans = []
        for lfp in eeg:

            f, pxx = sg.welch(
                lfp,
                fs=eegSrate,
                nperseg=10 * eegSrate,
                noverlap=5 * eegSrate,
                axis=-1,
            )
            f_theta = np.where((f > 5) & (f < 20))[0]
            area_in_freq = np.trapz(pxx[f_theta], x=f[f_theta])

            aucChans.append(area_in_freq)

        sorted_thetapow = np.argsort(np.asarray(aucChans))[::-1]

        return sorted_thetapow

    def detectBestChan(self, period):
        """Selects the best channel by computing area under the curve of spectral density"""
        channels = self._obj.goodchans
        eeg = self._obj.geteeg(chans=channels, timeRange=period)
        sorted_thetapow = self._getAUC(eeg=eeg)
        chans_thetapow = channels[sorted_thetapow]

        filename = self.files.bestThetachan
        best_theta_chans = {"chanorder": chans_thetapow}
        np.save(filename, best_theta_chans)
        self._load()  # load result immediately into Theta object.

    def getParams(self, lfp, lowtheta=1, hightheta=25):
        """Calculating Various theta related parameters

        Parameters
        ----------
        lfp : [type]
            lfp on which theta parameters are calculated.

        Returns
        -------
        [type]
            [description]
        """

        return signal_process.ThetaParams(
            lfp=lfp, fs=self._obj.lfpSrate, lowtheta=lowtheta, hightheta=hightheta
        )

    def getstrongTheta(
        self, lfp, lowthresh=0, highthresh=0.5, minDistance=300, minDuration=1250
    ):
        """Returns strong theta lfp. If it has multiple channels, then strong theta periods are calculated from that
        channel which has highest area under the curve in the theta frequency band. Parameters are applied on z-scored lfp.

        Parameters
        ----------
        lfp : array like, channels x time
            from which strong periods are concatenated and returned
        lowthresh : float, optional
            threshold above which it is considered strong, by default 0 which is mean of the selected channel
        highthresh : float, optional
            [description], by default 0.5
        minDistance : int, optional
            minimum gap between periods before they are merged, by default 300 samples
        minDuration : int, optional
            [description], by default 1250, which means theta period should atleast last for 1 second

        Returns
        -------
        [type]
            [description]
        """

        lfp_besttheta = lfp

        if lfp.ndim == 2:
            theta_order = self._getAUC(lfp)
            lfp_besttheta = lfp[theta_order[0], :]

        # ---- filtering --> zscore --> threshold --> strong theta periods ----
        thetalfp = signal_process.filter_sig.bandpass(lfp_besttheta, lf=4, hf=10)
        hil_theta = signal_process.hilbertfast(thetalfp)
        theta_amp = np.abs(hil_theta)

        zsc_theta = stats.zscore(theta_amp)
        thetaevents = mathutil.threshPeriods(
            zsc_theta,
            lowthresh=lowthresh,
            highthresh=highthresh,
            minDistance=minDistance,
            minDuration=minDuration,
        )

        theta_indices = []
        for (beg, end) in thetaevents:
            theta_indices.extend(np.arange(beg, end))
        theta_indices = np.asarray(theta_indices)

        strong_theta = np.take(lfp, theta_indices, axis=-1)
        weak_theta = np.delete(lfp, theta_indices, axis=-1)
        return strong_theta, weak_theta, theta_indices

    @staticmethod
    def phase_specfic_extraction(lfp, y, binsize=20, slideby=None):
        """Breaks y into theta phase specific components

        Parameters
        ----------
        lfp : array like
            reference lfp from which theta phases are estimated
        y : array like
            timeseries which is broken into components
        binsize : int, optional
            width of each bin in degrees, by default 20
        slideby : int, optional
            slide each bin by this amount in degrees, by default None

        Returns
        -------
        [list]
            list of broken signal into phase components
        """

        assert len(lfp) == len(y), "Both signals should be of same length"
        thetalfp = signal_process.filter_sig.bandpass(lfp, lf=1, hf=25)
        hil_theta = signal_process.hilbertfast(thetalfp)
        theta_angle = np.angle(hil_theta, deg=True) + 180  # range from 0-360 degree

        if slideby is None:
            slideby = binsize

        # --- sliding windows--------
        angle_bin = np.arange(0, 361)
        slide_angles = np.lib.stride_tricks.sliding_window_view(angle_bin, binsize)[
            ::slideby, :
        ]
        angle_centers = np.mean(slide_angles, axis=1)

        y_at_phase = []
        for phase in slide_angles:
            y_at_phase.append(
                y[np.where((theta_angle >= phase[0]) & (theta_angle <= phase[-1]))[0]]
            )

        return y_at_phase, angle_bin, angle_centers

    def plot(self):
        """Gives a comprehensive view of the detection process with some statistics and examples"""
        data = self._load()
        pxx = data["Pxx"]

    def csd(self, period, refchan, chans, window=1250):
        """Calculating current source density using laplacian method

        Parameters
        ----------
        period : array
            period over which theta cycles are averaged
        refchan : int or array
            channel whose theta peak will be considered. If array then median of lfp across all channels will be chosen
            for peak detection
        chans : array
            channels for lfp data
        window : int, optional
            time window around theta peak in number of samples, by default 1250

        Returns:
        ----------
        csd : dataclass,
            a dataclass return from signal_process module
        """
        eegSrate = self._obj.lfpSrate
        lfp_period = self._obj.geteeg(chans=chans, timeRange=period)
        lfp_period = signal_process.filter_sig.bandpass(lfp_period, lf=5, hf=12)

        theta_lfp = self._obj.geteeg(chans=refchan, timeRange=period)
        nChans = lfp_period.shape[0]
        # lfp_period, _, _ = self.getstrongTheta(lfp_period)

        # --- Selecting channel with strongest theta for calculating theta peak-----
        # chan_order = self._getAUC(lfp_period)
        # theta_lfp = signal_process.filter_sig.bandpass(
        #     lfp_period[chan_order[0], :], lf=5, hf=12, ax=-1)
        theta_lfp = signal_process.filter_sig.bandpass(theta_lfp, lf=5, hf=12)
        peak = sg.find_peaks(theta_lfp)[0]
        # Ignoring first and last second of data
        peak = peak[np.where((peak > 1250) & (peak < len(theta_lfp) - 1250))[0]]

        # ---- averaging around theta cycle ---------------
        avg_theta = np.zeros((nChans, window))
        for ind in peak:
            avg_theta = avg_theta + lfp_period[:, ind - window // 2 : ind + window // 2]
        avg_theta = avg_theta / len(peak)

        _, ycoord = self._obj.probemap.get(chans=chans)

        csd = signal_process.Csd(
            lfp=avg_theta, coords=ycoord, chan_label=chans, fs=eegSrate
        )
        csd.classic()

        return csd


class Gamma:
    """Events and analysis related to gamma oscillations"""

    def __init__(self, basepath):

        if isinstance(basepath, Recinfo):
            self._obj = basepath
        else:
            self._obj = Recinfo(basepath)

        # ------- defining file names ---------
        filePrefix = self._obj.files.filePrefix

        @dataclass
        class files:
            gamma: str = filePrefix.with_suffix(".gamma.npy")

        self.files = files()
        self._load()

    def _load(self):
        if (f := self.files.gamma).is_file():
            data = np.load(f, allow_pickle=True).item()
            self.bestchan = data["chanorder"][0]
            self.chansOrder = data["chanorder"]

    def get_peak_intervals(
        self,
        lfp,
        band=(25, 50),
        lowthresh=0,
        highthresh=1,
        minDistance=300,
        minDuration=125,
    ):
        """Returns strong theta lfp. If it has multiple channels, then strong theta periods are calculated from that channel which has highest area under the curve in the theta frequency band. Parameters are applied on z-scored lfp.

        Parameters
        ----------
        lfp : array like, channels x time
            from which strong periods are concatenated and returned
        lowthresh : float, optional
            threshold above which it is considered strong, by default 0 which is mean of the selected channel
        highthresh : float, optional
            [description], by default 0.5
        minDistance : int, optional
            minimum gap between periods before they are merged, by default 300 samples
        minDuration : int, optional
            [description], by default 1250, which means theta period should atleast last for 1 second

        Returns
        -------
        2D array
            start and end frames where events exceeded the set thresholds
        """

        # ---- filtering --> zscore --> threshold --> strong gamma periods ----
        gammalfp = signal_process.filter_sig.bandpass(lfp, lf=band[0], hf=band[1])
        hil_gamma = signal_process.hilbertfast(gammalfp)
        gamma_amp = np.abs(hil_gamma)

        zsc_gamma = stats.zscore(gamma_amp)
        peakevents = mathutil.threshPeriods(
            zsc_gamma,
            lowthresh=lowthresh,
            highthresh=highthresh,
            minDistance=minDistance,
            minDuration=minDuration,
        )

        return peakevents

    def csd(self, period, refchan, chans, band=(25, 50), window=1250):
        """Calculating current source density using laplacian method

        Parameters
        ----------
        period : array
            period over which theta cycles are averaged
        refchan : int or array
            channel whose theta peak will be considered. If array then median of lfp across all channels will be chosen for peak detection
        chans : array
            channels for lfp data
        window : int, optional
            time window around theta peak in number of samples, by default 1250

        Returns:
        ----------
        csd : dataclass,
            a dataclass return from signal_process module
        """
        lfp_period = self._obj.geteeg(chans=chans, timeRange=period)
        lfp_period = signal_process.filter_sig.bandpass(
            lfp_period, lf=band[0], hf=band[1]
        )

        gamma_lfp = self._obj.geteeg(chans=refchan, timeRange=period)
        nChans = lfp_period.shape[0]
        # lfp_period, _, _ = self.getstrongTheta(lfp_period)

        # --- Selecting channel with strongest theta for calculating theta peak-----
        # chan_order = self._getAUC(lfp_period)
        # gamma_lfp = signal_process.filter_sig.bandpass(
        #     lfp_period[chan_order[0], :], lf=5, hf=12, ax=-1)
        gamma_lfp = signal_process.filter_sig.bandpass(
            gamma_lfp, lf=band[0], hf=band[1]
        )
        peak = sg.find_peaks(gamma_lfp)[0]
        # Ignoring first and last second of data
        peak = peak[np.where((peak > 1250) & (peak < len(gamma_lfp) - 1250))[0]]

        # ---- averaging around theta cycle ---------------
        avg_theta = np.zeros((nChans, window))
        for ind in peak:
            avg_theta = avg_theta + lfp_period[:, ind - window // 2 : ind + window // 2]
        avg_theta = avg_theta / len(peak)

        _, ycoord = self._obj.probemap.get(chans=chans)

        csd = signal_process.Csd(lfp=avg_theta, coords=ycoord, chan_label=chans)
        csd.classic()

        return csd
