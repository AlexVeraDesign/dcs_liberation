import {
  useClearTgoDestinationMutation,
  useOpenNewTgoPackageDialogMutation,
  useOpenTgoInfoDialogMutation,
  useSetTgoDestinationMutation,
} from "../../api/liberationApi";
import { Tgo as TgoModel } from "../../api/liberationApi";
import backend from "../../api/backend";
import { MovementPath, MovementPathHandle } from "../controlpoints/MovementPath";
import SplitLines from "../splitlines/SplitLines";
import { Icon, LatLng, LatLngLiteral, Marker as LMarker, Point } from "leaflet";
import { Symbol as MilSymbol } from "milsymbol";
import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Marker, Tooltip } from "react-leaflet";

function iconForTgo(cp: TgoModel) {
  const symbol = new MilSymbol(cp.sidc, {
    size: 24,
  });

  return new Icon({
    iconUrl: symbol.toDataURL(),
    iconAnchor: new Point(symbol.getAnchor().x, symbol.getAnchor().y),
  });
}

function metersToNauticalMiles(meters: number) {
  return meters * 0.000539957;
}

function formatLatLng(latLng: LatLng) {
  const lat = latLng.lat.toFixed(2);
  const lng = latLng.lng.toFixed(2);
  const ns = latLng.lat >= 0 ? "N" : "S";
  const ew = latLng.lng >= 0 ? "E" : "W";
  return `${lat}&deg;${ns} ${lng}&deg;${ew}`;
}

function tooltipText(tgo: TgoModel) {
  const lines = [`${tgo.name} (${tgo.control_point_name})`];
  if (tgo.units.length > 0) {
    lines.push(...tgo.units);
  }
  return lines.join("<br />");
}

function destinationTooltipText(
  tgo: TgoModel,
  destinationish: LatLngLiteral,
  inRange: boolean
) {
  const destination = new LatLng(destinationish.lat, destinationish.lng);
  const distance = metersToNauticalMiles(destination.distanceTo(tgo.position)).toFixed(
    1
  );
  if (!inRange) {
    return `Out of range (${distance}nm away)`;
  }
  const dest = formatLatLng(destination);
  return `${tgo.name} moving ${distance}nm to ${dest} next turn`;
}

interface StaticTgoProps {
  tgo: TgoModel;
  children?: ReactNode;
}

function StaticTgo(props: StaticTgoProps) {
  const [openNewPackageDialog] = useOpenNewTgoPackageDialogMutation();
  const [openInfoDialog] = useOpenTgoInfoDialogMutation();
  return (
    <Marker
      position={props.tgo.position}
      icon={iconForTgo(props.tgo)}
      eventHandlers={{
        click: () => {
          openInfoDialog({ tgoId: props.tgo.id });
        },
        contextmenu: () => {
          openNewPackageDialog({ tgoId: props.tgo.id });
        },
      }}
    >
      <Tooltip>{props.children ?? <TgoTooltip tgo={props.tgo} />}</Tooltip>
    </Marker>
  );
}

function TgoTooltip(props: TgoProps) {
  return (
    <>
      {`${props.tgo.name} (${props.tgo.control_point_name})`}
      {props.tgo.units.length > 0 && (
        <>
          <br />
          <SplitLines items={props.tgo.units} />
        </>
      )}
    </>
  );
}

interface PrimaryMobileTgoProps {
  tgo: TgoModel;
}

function PrimaryMobileTgo(props: PrimaryMobileTgoProps) {
  const markerRef = useRef<LMarker | null>(null);
  const pathRef = useRef<MovementPathHandle | null>(null);
  const [hasDestination, setHasDestination] = useState<boolean>(
    props.tgo.destination != null
  );
  const [position, setPosition] = useState<LatLngLiteral>(
    props.tgo.destination ? props.tgo.destination : props.tgo.position
  );

  const setDestination = useCallback((destination: LatLng) => {
    setPosition(destination);
    setHasDestination(true);
  }, []);

  const resetDestination = useCallback(() => {
    setPosition(props.tgo.position);
    setHasDestination(false);
  }, [props]);

  const [openNewPackageDialog] = useOpenNewTgoPackageDialogMutation();
  const [openInfoDialog] = useOpenTgoInfoDialogMutation();
  const [putDestination, { isLoading }] = useSetTgoDestinationMutation();
  const [cancelTravel] = useClearTgoDestinationMutation();

  useEffect(() => {
    markerRef.current?.setTooltipContent(
      props.tgo.destination
        ? destinationTooltipText(props.tgo, props.tgo.destination, true)
        : tooltipText(props.tgo)
    );
  });

  return (
    <>
      <Marker
        position={position}
        icon={iconForTgo(props.tgo)}
        draggable={!isLoading}
        autoPan
        zIndexOffset={1000}
        opacity={props.tgo.destination ? 0.5 : 1}
        ref={(ref) => {
          if (ref != null) {
            markerRef.current = ref;
          }
        }}
        eventHandlers={{
          click: () => {
            if (!hasDestination) {
              openInfoDialog({ tgoId: props.tgo.id });
            }
          },
          contextmenu: () => {
            if (props.tgo.destination) {
              cancelTravel({ tgoId: props.tgo.id }).then(() => {
                resetDestination();
              });
            } else {
              openNewPackageDialog({ tgoId: props.tgo.id });
            }
          },
          drag: (event) => {
            const destination = event.target.getLatLng();
            backend
              .get(
                `/tgos/${props.tgo.id}/destination-in-range?lat=${destination.lat}&lng=${destination.lng}`
              )
              .then((inRange) => {
                markerRef.current?.setTooltipContent(
                  destinationTooltipText(props.tgo, destination, inRange.data)
                );
              });
            pathRef.current?.setDestination(destination);
          },
          dragend: async (event) => {
            const hadDestination = hasDestination;
            const currentPosition = new LatLng(position.lat, position.lng);
            const destination = event.target.getLatLng();
            setDestination(destination);
            try {
              await putDestination({
                tgoId: props.tgo.id,
                body: { lat: destination.lat, lng: destination.lng },
              }).unwrap();
            } catch (error) {
              console.error("setTgoDestination failed", error);
              if (hadDestination) {
                setDestination(currentPosition);
              } else {
                resetDestination();
              }
            }
          },
        }}
      >
        <Tooltip />
      </Marker>
      <MovementPath source={props.tgo.position} destination={position} ref={pathRef} />
    </>
  );
}

function SecondaryMobileTgo(props: PrimaryMobileTgoProps) {
  if (!props.tgo.destination) {
    return <></>;
  }
  return <StaticTgo tgo={props.tgo} />;
}

interface TgoProps {
  tgo: TgoModel;
}

export default function Tgo(props: TgoProps) {
  if (!props.tgo.mobile) {
    return <StaticTgo tgo={props.tgo} />;
  }
  return (
    <>
      <PrimaryMobileTgo tgo={props.tgo} key={props.tgo.destination ? 0 : 1} />
      <SecondaryMobileTgo tgo={props.tgo} />
    </>
  );
}
