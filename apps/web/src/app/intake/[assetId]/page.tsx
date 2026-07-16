import { ProblemIntake } from "@/features/problems/components/ProblemIntake";

type PageProps = {
  params: Promise<{ assetId: string }>;
};

export default async function ExistingAssetIntakePage({ params }: PageProps) {
  const { assetId } = await params;
  return <ProblemIntake existingAssetId={assetId} />;
}
