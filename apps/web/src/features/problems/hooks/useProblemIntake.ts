"use client";

import { useCallback, useEffect, useState } from "react";

import {
  asApiError,
  createRegionsBatch,
  detectProblemRegions,
  getAsset,
  getAssetProblems,
  uploadAsset,
} from "@/lib/api-client";
import type {
  AssetProblemCollection,
  BatchRegionCreate,
  BatchRegionCreateRequest,
  RegionDetectionRun,
  RequestState,
  SourceAsset,
} from "@/lib/contracts";

export function useProblemIntake(existingAssetId?: string) {
  const [assetState, setAssetState] = useState<RequestState<SourceAsset>>(
    existingAssetId ? { status: "pending" } : { status: "idle" },
  );
  const [collectionState, setCollectionState] = useState<
    RequestState<AssetProblemCollection>
  >(existingAssetId ? { status: "pending" } : { status: "idle" });
  const [detectionState, setDetectionState] = useState<RequestState<RegionDetectionRun>>({
    status: "idle",
  });
  const [batchState, setBatchState] = useState<RequestState<BatchRegionCreate>>({
    status: "idle",
  });
  useEffect(() => {
    if (!existingAssetId) return;
    const controller = new AbortController();
    void getAsset(existingAssetId, controller.signal)
      .then((asset) => {
        if (!controller.signal.aborted) setAssetState({ status: "success", data: asset });
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setAssetState({ status: "error", error: asApiError(error) });
        }
      });
    return () => controller.abort();
  }, [existingAssetId]);

  useEffect(() => {
    if (!existingAssetId) return;
    const controller = new AbortController();
    void getAssetProblems(existingAssetId, controller.signal)
      .then((collection) => {
        if (!controller.signal.aborted) {
          setCollectionState({ status: "success", data: collection });
        }
      })
      .catch((error: unknown) => {
        if (!controller.signal.aborted) {
          setCollectionState({ status: "error", error: asApiError(error) });
        }
      });
    return () => controller.abort();
  }, [existingAssetId]);

  const upload = useCallback(async (file: File): Promise<SourceAsset> => {
    setAssetState({ status: "pending" });
    setDetectionState({ status: "idle" });
    setBatchState({ status: "idle" });
    setCollectionState({ status: "idle" });
    try {
      const asset = await uploadAsset(file);
      setAssetState({ status: "success", data: asset });
      return asset;
    } catch (error) {
      const apiError = asApiError(error);
      setAssetState({ status: "error", error: apiError });
      throw apiError;
    }
  }, []);

  const detect = useCallback(async (assetId: string): Promise<RegionDetectionRun> => {
    setDetectionState({ status: "pending" });
    setBatchState({ status: "idle" });
    try {
      const detection = await detectProblemRegions(assetId);
      setDetectionState({ status: "success", data: detection });
      return detection;
    } catch (error) {
      const apiError = asApiError(error);
      setDetectionState({ status: "error", error: apiError });
      throw apiError;
    }
  }, []);

  const saveRegions = useCallback(
    async (assetId: string, request: BatchRegionCreateRequest): Promise<BatchRegionCreate> => {
      setBatchState({ status: "pending" });
      try {
        const batch = await createRegionsBatch(assetId, request);
        setBatchState({ status: "success", data: batch });
        return batch;
      } catch (error) {
        const apiError = asApiError(error);
        setBatchState({ status: "error", error: apiError });
        throw apiError;
      }
    },
    [],
  );

  const refreshAssetProblems = useCallback(
    async (assetId: string): Promise<AssetProblemCollection> => {
      setCollectionState({ status: "pending" });
      try {
        const collection = await getAssetProblems(assetId);
        setCollectionState({ status: "success", data: collection });
        return collection;
      } catch (error) {
        const apiError = asApiError(error);
        setCollectionState({ status: "error", error: apiError });
        throw apiError;
      }
    },
    [],
  );

  const resetBatch = useCallback(() => {
    setBatchState({ status: "idle" });
  }, []);

  return {
    assetState,
    collectionState,
    detectionState,
    batchState,
    upload,
    detect,
    saveRegions,
    refreshAssetProblems,
    resetBatch,
  };
}
